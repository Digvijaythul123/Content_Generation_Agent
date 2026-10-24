// Cloud scheduler for @buddha.realteachings.
//
// The Mac app uploads a scheduled post's media to R2 and sends the job here.
// Every minute this Worker publishes due jobs step by step (Instagram, first
// comment, Facebook, Threads, then deletes the R2 copies), so posts go out
// on time even when the Mac is asleep. The Mac app reads the results back.
//
// Storage (KV binding JOBS), kept small for the free plan:
//   "index"   {postId: dueIso}  read once a minute (no KV list calls)
//   "job:ID"  the job and its progress   (written only when it changes)
//   "tokens"  access tokens; the Instagram and Threads ones are refreshed weekly

const IG = "https://graph.instagram.com/v23.0";
const FB = "https://graph.facebook.com/v23.0";
const FB_UPLOAD = "https://rupload.facebook.com/video-upload/v23.0";
const THREADS = "https://graph.threads.net/v1.0";
// Retry waits (minutes) for network trouble and rate limits.
const RETRY_MINUTES = [1, 2, 5, 10, 20, 30];
const RATE_LIMIT_CODES = new Set([4, 17, 32, 368, 613]);
// Give up waiting on a platform's processing after this long.
const WAIT_LIMIT_MINUTES = 30;
const TOKEN_REFRESH_DAYS = 7;

class ApiError extends Error {
  constructor(message, { transient = false } = {}) {
    super(message);
    this.transient = transient;
  }
}

// ---------------------------------------------------------------- helpers

async function call(url, { method = "GET", params = {}, headers = {}, token } = {}) {
  const body = new URLSearchParams();
  const target = new URL(url);
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (method === "GET") target.searchParams.set(key, String(value));
    else body.set(key, String(value));
  }
  if (token) {
    if (method === "GET") target.searchParams.set("access_token", token);
    else body.set("access_token", token);
  }
  let response;
  try {
    response = await fetch(target, method === "GET" ? { headers } : { method, headers, body });
  } catch (error) {
    throw new ApiError(`Could not reach ${target.host}.`, { transient: true });
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok || payload.error) {
    const details = payload.error || {};
    const message = details.error_user_msg || details.message || "no error details";
    const transient = response.status >= 500 || RATE_LIMIT_CODES.has(details.code)
      || /limit how often/i.test(message);
    // Never echo the URL: it can carry a token.
    throw new ApiError(`${target.host} returned HTTP ${response.status}: ${message}`, { transient });
  }
  return payload;
}

const minutesFrom = (date, minutes) => new Date(date.getTime() + minutes * 60000).toISOString();

async function readJson(env, key, fallback = null) {
  const value = await env.JOBS.get(key, "json");
  return value ?? fallback;
}

async function saveJob(env, job) {
  await env.JOBS.put(`job:${job.id}`, JSON.stringify(job));
}

async function setIndex(env, id, due) {
  const index = await readJson(env, "index", {});
  if (due) index[id] = due;
  else delete index[id];
  await env.JOBS.put("index", JSON.stringify(index));
}

function note(job, text) {
  job.log = [...(job.log || []).slice(-19), `${new Date().toISOString()} ${text}`];
}

// ------------------------------------------------------------- the steps

// Each step returns "next" (go on now), "wait" (check again next minute),
// or "done". A step may move job.stage forward.
const steps = {
  async ig_create(job, tokens) {
    const account = tokens.instagram_account_id;
    const token = tokens.instagram_token;
    if (job.kind === "carousel") {
      job.ig.children = job.ig.children || [];
      for (const url of job.media.image_urls.slice(job.ig.children.length)) {
        const child = await call(`${IG}/${account}/media`, {
          method: "POST", token,
          params: { image_url: url, is_carousel_item: "true", is_ai_generated: "true" },
        });
        job.ig.children.push(child.id);
      }
      job.stage = "ig_children_wait";
      return "next";
    }
    const params = job.kind === "reel"
      ? {
        media_type: "REELS", video_url: job.media.video_url, caption: job.caption,
        share_to_feed: "true", is_ai_generated: "true",
        cover_url: job.media.cover_url, thumb_offset: job.thumb_offset_ms,
      }
      : { image_url: job.media.image_urls[0], caption: job.caption, is_ai_generated: "true" };
    const container = await call(`${IG}/${account}/media`, { method: "POST", token, params });
    job.ig.container_id = container.id;
    job.ig.waiting_since = new Date().toISOString();
    job.stage = "ig_wait";
    return "next";
  },

  async ig_children_wait(job, tokens) {
    for (const child of job.ig.children) {
      const status = await call(`${IG}/${child}`, { token: tokens.instagram_token, params: { fields: "status_code" } });
      if (status.status_code === "ERROR") throw new ApiError("Instagram could not process a carousel slide.");
      if (status.status_code !== "FINISHED") return "wait";
    }
    const container = await call(`${IG}/${tokens.instagram_account_id}/media`, {
      method: "POST", token: tokens.instagram_token,
      params: { media_type: "CAROUSEL", children: job.ig.children.join(","), caption: job.caption },
    });
    job.ig.container_id = container.id;
    job.ig.waiting_since = new Date().toISOString();
    job.stage = "ig_wait";
    return "next";
  },

  async ig_wait(job, tokens) {
    const token = tokens.instagram_token;
    const status = await call(`${IG}/${job.ig.container_id}`, { token, params: { fields: "status_code" } });
    if (status.status_code === "ERROR" || status.status_code === "EXPIRED") {
      throw new ApiError(`Instagram could not process the media (${status.status_code}).`);
    }
    if (status.status_code !== "FINISHED") {
      if (Date.now() - Date.parse(job.ig.waiting_since) > WAIT_LIMIT_MINUTES * 60000) {
        throw new ApiError("Instagram took too long to process the media.");
      }
      return "wait";
    }
    if (job.dry_run) {
      note(job, "dry run: Instagram accepted the media; not published");
      job.stage = "cleanup";
      return "next";
    }
    const published = await call(`${IG}/${tokens.instagram_account_id}/media_publish`, {
      method: "POST", token, params: { creation_id: job.ig.container_id },
    });
    job.ig.media_id = published.id;
    job.ig.published_at = new Date().toISOString();
    try {
      job.ig.permalink = (await call(`${IG}/${published.id}`, { token, params: { fields: "permalink" } })).permalink;
    } catch {
      job.ig.permalink = null;
    }
    note(job, `published on Instagram ${job.ig.permalink || published.id}`);
    job.stage = "comment";
    return "next";
  },

  // The steps below never block the post: a failure is recorded and the
  // next platform still runs.
  async comment(job, tokens) {
    if (job.first_comment) {
      try {
        const comment = await call(`${IG}/${job.ig.media_id}/comments`, {
          method: "POST", token: tokens.instagram_token, params: { message: job.first_comment },
        });
        job.comment_id = comment.id;
      } catch (error) {
        job.errors.comment = error.message;
      }
    }
    job.stage = "facebook";
    return "next";
  },

  async facebook(job, tokens) {
    if (!job.platforms.facebook || !tokens.facebook_page_token) {
      job.stage = "threads";
      return "next";
    }
    const page = tokens.facebook_page_id;
    const token = tokens.facebook_page_token;
    try {
      if (job.kind === "reel") {
        const start = await call(`${FB}/${page}/video_reels`, { method: "POST", token, params: { upload_phase: "start" } });
        // Facebook fetches the video from R2 itself.
        const upload = await fetch(`${FB_UPLOAD}/${start.video_id}`, {
          method: "POST",
          headers: { Authorization: `OAuth ${token}`, file_url: job.media.video_url },
        });
        if (!upload.ok) throw new ApiError(`Facebook upload failed (HTTP ${upload.status}).`);
        await call(`${FB}/${page}/video_reels`, {
          method: "POST", token,
          params: { upload_phase: "finish", video_id: start.video_id, video_state: "PUBLISHED", description: job.caption },
        });
        job.facebook = { video_id: start.video_id };
      } else if (job.media.image_urls.length > 1) {
        const ids = [];
        for (const url of job.media.image_urls) {
          ids.push((await call(`${FB}/${page}/photos`, { method: "POST", token, params: { url, published: "false" } })).id);
        }
        const params = { message: job.caption };
        ids.forEach((id, index) => { params[`attached_media[${index}]`] = JSON.stringify({ media_fbid: id }); });
        const post = await call(`${FB}/${page}/feed`, { method: "POST", token, params });
        job.facebook = { post_id: post.id };
      } else {
        const photo = await call(`${FB}/${page}/photos`, {
          method: "POST", token, params: { url: job.media.image_urls[0], message: job.caption, published: "true" },
        });
        job.facebook = { post_id: photo.post_id || photo.id };
      }
      note(job, "posted to Facebook");
    } catch (error) {
      job.errors.facebook = error.message;
    }
    job.stage = "threads";
    return "next";
  },

  async threads(job, tokens) {
    if (!job.platforms.threads || !tokens.threads_token) {
      job.stage = "cleanup";
      return "next";
    }
    const user = tokens.threads_user_id;
    const token = tokens.threads_token;
    try {
      let params;
      if (job.kind === "reel") {
        params = { media_type: "VIDEO", video_url: job.media.video_url, text: job.caption };
      } else if (job.media.image_urls.length > 1) {
        const children = [];
        for (const url of job.media.image_urls) {
          children.push((await call(`${THREADS}/${user}/threads`, {
            method: "POST", token, params: { media_type: "IMAGE", image_url: url, is_carousel_item: "true" },
          })).id);
        }
        params = { media_type: "CAROUSEL", children: children.join(","), text: job.caption };
      } else {
        params = { media_type: "IMAGE", image_url: job.media.image_urls[0], text: job.caption };
      }
      const container = await call(`${THREADS}/${user}/threads`, { method: "POST", token, params });
      job.threads = { container_id: container.id, waiting_since: new Date().toISOString() };
      job.stage = "threads_wait";
    } catch (error) {
      job.errors.threads = error.message;
      job.stage = "cleanup";
    }
    return "next";
  },

  async threads_wait(job, tokens) {
    const token = tokens.threads_token;
    try {
      const status = await call(`${THREADS}/${job.threads.container_id}`, { token, params: { fields: "status,error_message" } });
      if (status.status === "ERROR" || status.status === "EXPIRED") {
        throw new ApiError(`Threads could not process the media: ${status.error_message || status.status}`);
      }
      if (status.status !== "FINISHED") {
        if (Date.now() - Date.parse(job.threads.waiting_since) > WAIT_LIMIT_MINUTES * 60000) {
          throw new ApiError("Threads took too long to process the media.");
        }
        return "wait";
      }
      const published = await call(`${THREADS}/${tokens.threads_user_id}/threads_publish`, {
        method: "POST", token, params: { creation_id: job.threads.container_id },
      });
      job.threads.media_id = published.id;
      try {
        job.threads.permalink = (await call(`${THREADS}/${published.id}`, { token, params: { fields: "permalink" } })).permalink;
      } catch {
        job.threads.permalink = null;
      }
      note(job, "posted to Threads");
    } catch (error) {
      job.errors.threads = error.message;
    }
    job.stage = "cleanup";
    return "next";
  },

  async cleanup(job, _tokens, env) {
    // Every platform has its own copy now; remove the public R2 files.
    if (job.r2_keys?.length) await env.MEDIA.delete(job.r2_keys);
    job.status = "done";
    job.stage = "finished";
    job.finished_at = new Date().toISOString();
    return "done";
  },
};

async function advance(job, tokens, env) {
  for (let guard = 0; guard < 12; guard++) {
    const step = steps[job.stage];
    if (!step) throw new ApiError(`Unknown step ${job.stage}.`);
    const outcome = await step(job, tokens, env);
    if (outcome !== "next") return outcome;
  }
  return "wait";
}

// ------------------------------------------------------------ the minute

async function refreshTokens(env, tokens) {
  const last = tokens.refreshed_at ? Date.parse(tokens.refreshed_at) : 0;
  if (Date.now() - last < TOKEN_REFRESH_DAYS * 86400000) return;
  const changes = { refreshed_at: new Date().toISOString() };
  try {
    if (tokens.instagram_token) {
      const result = await call("https://graph.instagram.com/refresh_access_token", {
        token: tokens.instagram_token, params: { grant_type: "ig_refresh_token" },
      });
      if (result.access_token) changes.instagram_token = result.access_token;
    }
    if (tokens.threads_token) {
      const result = await call("https://graph.threads.net/refresh_access_token", {
        token: tokens.threads_token, params: { grant_type: "th_refresh_token" },
      });
      if (result.access_token) changes.threads_token = result.access_token;
    }
  } catch (error) {
    changes.refresh_error = error.message;
  }
  await env.JOBS.put("tokens", JSON.stringify({ ...tokens, ...changes }));
}

async function tick(env) {
  const index = await readJson(env, "index", {});
  const now = new Date();
  const due = Object.entries(index).filter(([, when]) => Date.parse(when) <= now.getTime());
  if (!due.length) return { checked: 0 };
  const tokens = await readJson(env, "tokens", {});
  if (!tokens.instagram_token) return { checked: 0, error: "no Instagram token" };
  let checked = 0;
  for (const [id] of due) {
    const job = await readJson(env, `job:${id}`);
    if (!job || job.status !== "queued") {
      await setIndex(env, id, null);
      continue;
    }
    checked += 1;
    const before = JSON.stringify(job);
    try {
      const outcome = await advance(job, tokens, env);
      if (outcome === "done") await setIndex(env, id, null);
      job.attempts = 0;
    } catch (error) {
      job.attempts = (job.attempts || 0) + 1;
      job.last_error = error.message;
      note(job, `error: ${error.message}`);
      if (error.transient && job.attempts <= RETRY_MINUTES.length) {
        // Try again later; the index holds the next attempt time.
        await setIndex(env, id, minutesFrom(now, RETRY_MINUTES[job.attempts - 1]));
      } else if (!job.ig?.media_id) {
        job.status = "failed";
        await setIndex(env, id, null);
      } else {
        // Instagram is done; a later step failing must not undo that.
        job.stage = "cleanup";
        await advance(job, tokens, env).catch(() => {});
        await setIndex(env, id, null);
      }
    }
    if (JSON.stringify(job) !== before) await saveJob(env, job);
  }
  await refreshTokens(env, tokens);
  return { checked };
}

// -------------------------------------------------------------- the API

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

function authorised(request, env) {
  const expected = env.SCHEDULER_SECRET;
  const given = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  return Boolean(expected) && given.length === expected.length && given === expected;
}

const JOB_FIELDS = [
  "id", "due", "kind", "media", "r2_keys", "caption", "first_comment",
  "thumb_offset_ms", "platforms", "dry_run",
];

async function handle(request, env) {
  if (!authorised(request, env)) return json({ error: "unauthorised" }, 401);
  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts[0] === "health") {
    const tokens = await readJson(env, "tokens", {});
    const index = await readJson(env, "index", {});
    return json({
      ok: true, queued: Object.keys(index).length,
      tokens: {
        instagram: Boolean(tokens.instagram_token), facebook: Boolean(tokens.facebook_page_token),
        threads: Boolean(tokens.threads_token),
      },
      refreshed_at: tokens.refreshed_at || null, refresh_error: tokens.refresh_error || null,
    });
  }
  if (parts[0] === "tokens" && request.method === "PUT") {
    const current = await readJson(env, "tokens", {});
    const update = await request.json();
    await env.JOBS.put("tokens", JSON.stringify({ ...current, ...update }));
    return json({ ok: true });
  }
  if (parts[0] === "run" && request.method === "POST") {
    return json(await tick(env));
  }
  if (parts[0] !== "jobs") return json({ error: "not found" }, 404);
  const id = parts[1];
  if (!id && request.method === "GET") {
    // Results the Mac app has not collected yet, plus queued jobs.
    const ids = (url.searchParams.get("ids") || "").split(",").filter(Boolean);
    const jobs = [];
    for (const each of ids) {
      const job = await readJson(env, `job:${each}`);
      if (job) jobs.push(job);
    }
    return json({ jobs });
  }
  if (!id || !/^[A-Za-z0-9_-]{1,64}$/.test(id)) return json({ error: "bad job id" }, 400);
  if (request.method === "GET") {
    const job = await readJson(env, `job:${id}`);
    return job ? json(job) : json({ error: "not found" }, 404);
  }
  if (request.method === "DELETE") {
    const job = await readJson(env, `job:${id}`);
    if (job && job.status === "queued" && job.stage !== "ig_create") {
      return json({ error: "this job is being published right now" }, 409);
    }
    await env.JOBS.delete(`job:${id}`);
    await setIndex(env, id, null);
    return json({ ok: true });
  }
  if (request.method === "PUT") {
    const existing = await readJson(env, `job:${id}`);
    if (existing && (existing.status !== "queued" || existing.stage !== "ig_create")) {
      return json({ error: "this job has already started" }, 409);
    }
    const body = await request.json();
    const job = { status: "queued", stage: "ig_create", ig: {}, errors: {}, attempts: 0, log: [] };
    for (const field of JOB_FIELDS) if (field in body) job[field] = body[field];
    job.id = id;
    if (!job.due || Number.isNaN(Date.parse(job.due))) return json({ error: "due must be a date" }, 400);
    if (!["reel", "image", "carousel"].includes(job.kind)) return json({ error: "unknown kind" }, 400);
    note(job, `queued for ${job.due}`);
    await saveJob(env, job);
    await setIndex(env, id, job.due);
    return json({ ok: true, job });
  }
  return json({ error: "method not allowed" }, 405);
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch (error) {
      return json({ error: error.message }, 500);
    }
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(tick(env));
  },
};
