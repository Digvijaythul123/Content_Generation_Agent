# AI Content Creation Platform

## Purpose

This repository is a local Python prototype for generating and reviewing
short-form content. Its intended direction is a configurable content platform
whose primary output is short-form video content. Development is planned as a
solo-developer-friendly modular monolith; distributed infrastructure is not a
goal.

The status labels in this document distinguish shipped behavior from planned
work:

- **[CURRENT]** Implemented in this repository.
- **[NEXT]** A reasonable near-term increment; not implemented yet.
- **[FUTURE]** A longer-term capability that depends on earlier work.

## Capability status

| Capability | Status | What that means today |
|---|---|---|
| Profile-based content generation | [CURRENT] | YAML profiles include Critical Thinking / Rational Thoughts, Comedy, and QA Engineering & AI. |
| Optional publisher brand | [CURRENT] | buddha.realteachings and Life Is a Glitch are configured; generation can also explicitly omit a brand. |
| Brief input and JSON content records | [CURRENT] | The CLI accepts a brief and saves a local JSON draft. |
| Draft review and approval | [CURRENT] | The local workspace reviews posts and Reels; CLI commands also remain available. |
| Scene and visual preparation | [CURRENT] | Commands produce scene text, image prompts, and a master video prompt. |
| Single-page social posts | [CURRENT] | The pipeline generates 4:5 Instagram Feed or LinkedIn post copy and a ready-to-use design prompt with exact copy and optional diagram labels. |
| LinkedIn text posts | [CURRENT] | QA Engineering & AI generates ready-to-publish post copy and a topic-specific image-generation prompt to copy into an image tool; it does not generate the image file. |
| Buddha's teachings content | [CURRENT] | The `rational_thoughts` profile is now **Buddha's Teachings**: a worldwide Buddhist audience, all traditions labelled, verified quotes only, and a lens in the Buddha's own "test it in your life" spirit. The thinker library holds the Buddha (default for new drafts), Ambedkar, Phule, and Osho. 14 story modes (including Mirror, One-Liner, Dialogue with a young monk, Real or Fake? quote quiz, and four illustrated modes: Mind States, Numbered List, Illustrated Metaphor, Parable Card), plain-English rules for all copy, and rotating world sceneries and weather for the art. |
| One-image Reels | [CURRENT] | `--format image_reel --platform instagram` writes short on-screen copy, a 9:16 art prompt, and a music cue. After approval and artwork, rendering produces a 1080×1920 cover and an 8s MP4 with a slow push-in, lines that fade in one by one, an optional effect (sparks, meteors, rain, snow, sunlight), music from `music/`, and an optional closing line in the last 2 seconds. |
| QA topic pillars | [CURRENT] | Optionally focus QA Engineering & AI drafts on one of eight pillars; multi-draft batches rotate through them when none is selected. |
| Optional Comedy category | [CURRENT] | Select Comedy independently of format, optionally choose one of ten subtypes, and generate Reel, single-page, or explicitly requested LinkedIn drafts without changing their output fields. Comedy batches can create up to ten drafts and rotate across subtypes. |
| Additional profiles, brands, and formats | [NEXT] | The data-driven direction exists, but broader profile and platform coverage remains incomplete. |
| Structured storyboard parsing | [CURRENT] | Timed or untimed scene beats are saved as JSON and readable text; richer review/edit flows remain [NEXT]. |
| Character, environment, camera, and music plans | [NEXT] | Reusable, independently reviewable plans are not yet modeled. |
| AI video rendering | [FUTURE] | No video provider integration or rendered video output exists. |
| Recurring 3D characters and reusable asset library | [FUTURE] | Not implemented. |
| Instagram Feed publishing | [CURRENT] | Approved single-image posts render to a 1080×1350 JPEG and carousels to one JPEG per slide, then publish (or schedule) through the Instagram API after explicit confirmation. |
| Carousels (swipe posts) | [CURRENT] | `--format carousel --platform instagram_feed`: a cover hook, 3-7 one-line slides, and a closing slide; one cover artwork, reused blurred behind the inner slides. |
| Facebook Page | [CURRENT] | After Instagram, Reels go to the Page as Reels, images as photo posts, and carousels as one multi-photo post. Facebook failures never undo the Instagram post; network and "posting too often" errors retry automatically. |
| Engagement tools | [CURRENT] | Closing call-to-action line on Reels, a numbered series ("Day 4 of 30"), a first comment to copy and pin, and Simplify / New wording rewrites of a post's text. |
| One-image Reel publishing and scheduling | [CURRENT] | After review on a Reel's Instagram tab (caption editor, 5-hashtag check, music choice), **Publish Reel now** uploads the MP4 to R2 and posts it through the Instagram API; **Schedule** queues it for `scripts.publish_scheduled`. Royalty-free tracks in `music/` are mixed in, because the API cannot add Instagram's music library. |
| Analytics | [CURRENT] | The review UI's Performance section lists each published post's hashtags, reach, Instagram views, Facebook views, and total views (what the Instagram app shows), sorted by reach, plus averages per story mode, visual style, and thinker. |

## Current workflow

```text
Brief + Brand + Content Profile + Format + Platform
    -> optional subtype guidance for the selected profile
    -> generated Reel, single-page post, or LinkedIn text post draft
    -> local JSON record
    -> human review / approval
    -> Reel: structured storyboard + image prompt + master video prompt
    -> Single-page: post copy + design prompt
    -> LinkedIn text post: ready-to-publish post copy
```

**[CURRENT]** The model client calls an Ollama-compatible endpoint; set
`MODEL_ENDPOINT` and `MODEL_NAME` in `.env` to change it.
Content and text assets are stored locally. The visual preparation pipeline
creates prompts only; it does not create images, animation, or video. The
single-page workflow saves records under `generated_posts/` and design prompts
under `generated_assets/`.

## Domain concepts

- **Content profile**: editorial mode such as Comedy, Finance, or Critical
  Thinking / Rational Thoughts. It defines audience, goals, voice, constraints,
  and profile visual direction.
- **Brand**: publisher identity, brand voice, reusable identity, and defaults.
  A brand can use multiple content profiles.
- **Format**: output shape, such as Instagram Reel, YouTube Short, LinkedIn
  text post, single-page graphic, thread, or blog article.
- **Platform**: destination and its capabilities or publishing constraints.

**Format is not a content profile.** Critical Thinking / Rational Thoughts and
QA Engineering & AI are editorial profiles; Instagram Reel is a format; Instagram is a platform.
A brand is optional publisher identity, not an editorial category. A profile should work across
compatible brands, formats, and platforms without niche-specific branches in
the shared pipeline.

## Running the current CLI

Run commands from the repository root using Python module invocation:

```bash
python3 -m scripts.main --profile comedy \
  --subtype pov \
  --brief "Plans I hoped would be cancelled"
python3 -m scripts.main --profile comedy \
  --brief "A relatable office mix-up with an unexpected punchline"
python3 -m scripts.main --category comedy \
  --comedy-subtype pov --brief "Plans I hoped would be cancelled"
python3 -m scripts.main --category comedy --count 10 \
  --brief "Ten unrelated modern-adult-life jokes"
python3 -m scripts.main --category comedy \
  --format single_page --platform instagram_feed \
  --comedy-subtype dark_uncomfortable \
  --brief "A funny visual about the five-year plan"
python3 -m scripts.main --profile rational_thoughts \
  --format single_page --platform instagram_feed \
  --brief "Explain why confidence is not evidence."
python3 -m scripts.main --profile rational_thoughts \
  --thinker buddha --subtype comedy
python3 -m scripts.main --profile rational_thoughts --count 6
python3 -m scripts.main --profile rational_thoughts --format image_reel \
  --platform instagram --thinker buddha --subtype thoughtful
python3 -m scripts.publish_post post_009 --art-file ~/Downloads/art.png
python3 -m scripts.main --profile qa_engineering_ai \
  --format linkedin_text_post --platform linkedin \
  --subtype llm_testing \
  --brief "Explain how to investigate flaky tests."
python3 -m scripts.main --profile qa_engineering_ai \
  --format single_page --platform linkedin \
  --brief "Share one practical lesson about test automation."
python3 -m scripts.review_ui
python3 -m scripts.list_reels
python3 -m scripts.approve_reel reel_017
python3 -m scripts.storyboard_generator reel_017
python3 -m scripts.prepare_reel reel_017
```

`scripts.prepare_reel` creates a validated storyboard at
`generated_videos/<reel_id>_storyboard.json`, exports a readable
`<reel_id>_scenes.txt`, generates image prompts, and composes a master video
prompt. Timed beats retain their source timecodes; untimed legacy scripts stay
untimed. Image-prompt generation calls the configured model. No stage renders
an image or video. See the individual commands under [scripts/](./scripts/).
The older `scripts.scene_generator` command remains as a compatibility alias
for storyboard generation.

`scripts.review_ui` opens a local-only browser workspace at
`http://127.0.0.1:8765`. It lists saved Reels, single-page posts, and LinkedIn
text posts with their
statuses, provides dashboard counts and activity, and lets you generate
drafts by brand, profile, optional profile-specific subtype, format, platform,
and optional brief. Subtypes appear only for profiles that define them. Select a
content item to review its details, approve/reject it, regenerate it as a new
draft, inspect format-specific production stages, preview text artifacts inline
with one-click copy and preview generated media,
and review its local activity history. Approved Reels can run storyboard,
scene-plan, image-prompt, and master video-prompt stages individually;
approved single-page posts can refresh their design prompt. LinkedIn text posts
show ready-to-publish copy without image-prompt actions. Approved Instagram
Feed posts gain an Instagram tab: render the image, review it with the caption,
then publish (see below). Video rendering is not integrated. Generation and AI-backed production stages use
the same configured model service as the CLI.

## Publishing to Instagram

**[CURRENT]** Single-page posts on the `instagram_feed` platform can be
published from the review UI's Instagram tab or the CLI:

```bash
python3 -m scripts.publish_post post_008 --render-only  # render for review
python3 -m scripts.publish_post post_008 --dry-run      # upload, print URL, do not post
python3 -m scripts.publish_post post_008                # confirm, then publish
python3 -m scripts.publish_post post_008 --new-art      # repaint artwork (paid) and re-render
python3 -m scripts.publish_post --check                 # verify the Instagram connection
python3 -m scripts.publish_post --refresh-token         # extend the 60-day token
```

**Layouts.** Each brand's `template.layout` picks the look: `classic` is a
text-only card; `quote_painting` (the `default` brand) first has Gemini paint
background artwork from the post's design prompt and the brand's `art_style`
(no text in the art), then overlays the exact copy on the left. Wrap key words
in `**double asterisks**` to highlight them in the accent colour; the
generation prompt asks the model to do this. Artwork is its own review stage,
so you can repaint it without changing the copy; repainting clears the stale
render.

In the review UI's Instagram tab, unpublished posts also have:

- **Edit on-image text**: change the title, main point, and supporting copy
  that the render draws (re-rendering alone redraws the same saved words).
- **Layout** for feed posts: *Poster* (`templates/feed_poster.html`, words
  over open space at the top) or *Standard* (the brand layout).
- **Effect** for Reels (video only): drifting sparks, meteor shower
  (shooting stars across the upper sky), rain, or sunlight rays. Each moves
  under the text; change it and render the video again.
- **Convert to Reel**: feed posts are still images, so this turns one into a
  one-image Reel for video and music; add new 9:16 art afterwards.
- **Scenery and Weather**: where the art is set (22 places, from desert dunes
  to cave temples) and its light (overcast, monsoon rain, mist, snow, night,
  and more). New drafts rotate them; changing them rewrites the art prompt.
  **Make the current image look like this weather** tints existing art
  instead (rain and snow add their effect).
- **Closing line** (Reels) and **Part of the series**: a call to action in
  the last 2 seconds of the video, and a "Day N of 30" label and caption line.
- **First comment**: suggested text (source and question) to post and pin.
- **Schedule** for Reels, single-image posts, and carousels, and **Also post
  to my Facebook Page** (on by default when the Page is connected).

Always make art from **Copy art prompt**, not the Content tab's scene notes:
the art prompt adds the style, scenery, weather, and no-lettering rules.

**Illustrated story modes** (Mind states, Numbered list, Illustrated
metaphor, Parable card) work the other way round: the image tool draws the
words. Their art prompt lists the exact headline, lines, and handle from the
post's text, and the uploaded picture is the finished post (no overlay; Reels
still get a gentle push-in, music, and effects). Use ChatGPT or Gemini for
these, check the spelling, and after editing the text copy the updated art
prompt and make the art again.

Art prompts never mention text, letters, or captions: image tools such as
Copilot (DALL-E) tend to paint any words the prompt names. If a render shows
the copy twice, the uploaded artwork already contains words; make it again.

Artwork sources (`ART_PROVIDER` in `.env`):

- `cloudflare` (default): Flux Schnell on Cloudflare Workers AI, inside the
  free daily allowance. Needs `CLOUDFLARE_AI_TOKEN` (Workers AI permission)
  and your account ID (`R2_ACCOUNT_ID` is reused).
- `gemini`: Nano Banana; needs `GEMINI_API_KEY` on a project with billing
  enabled (the free tier allows no image generation).
- Manual, free: in the Instagram tab use **Copy art prompt**, generate the
  image in the Gemini or ChatGPT app, then **Upload artwork**. CLI:
  `--art-prompt` and `--art-file PATH`.

Flow: Approved → render `generated_assets/<post_id>_instagram.jpg` from
`templates/instagram_feed.html` (brand colours from the brand YAML `template`
section) → **you review it locally** → on confirmation, upload to Cloudflare R2
→ Instagram fetches it → publish → the hosted copy is deleted. The record
becomes `Published` with `instagram_media_id`, `instagram_permalink`, and
`published_at`. Nothing leaves your computer before you confirm.

One-time setup:

1. Add `GEMINI_API_KEY` from https://aistudio.google.com/apikey if your brand
   uses the `quote_painting` layout.
2. `python3 -m pip install -r requirements.txt` and
   `python3 -m playwright install chromium`.
3. Instagram account must be Creator or Business.
4. At developers.facebook.com create an app, add the **Instagram** product,
   and choose *API setup with Instagram login*. Add your account as an
   Instagram tester and accept the invite in the Instagram app.
5. Generate a token with `instagram_business_basic` and
   `instagram_business_content_publish`. Copy the token and the Instagram
   account ID into `.env` (see `.env.example`).
6. Create a Cloudflare R2 bucket, enable its public `r2.dev` URL, create an
   API token with Object Read & Write, and add the R2 values to `.env`.

Limits: JPEG images only, captions ≤ 2,200 characters and ≤ 30 hashtags, and
100 API-published posts per rolling 24 hours.

## Configuration and storage

**[CURRENT]** Brand, profile, format, and platform YAML live under `config/`.
Reusable generation instructions are in `prompts/`. Reel records are JSON in
`generated_reels/`; single-page and LinkedIn text-post records are JSON in
`generated_posts/`.
Storyboard records are JSON and scene/master prompts are text under
`generated_videos/`; image/design prompts are text under `generated_images/`
and `generated_assets/`.

Local paths resolve from the project directory. Keep credentials out of YAML,
JSON records, and prompts. The current provider endpoint and model are fixed
in code, so provider configuration is a planned task, not an existing feature.

## Planned direction

- **[NEXT]** Expand profile and brand configuration; extend storyboard
  contracts with richer visual planning, continuity, and editing/review.
- **[NEXT]** Add a prompt registry and explicit visual planning for style,
  characters, environments, camera, voiceover, and music.
- **[FUTURE]** Add an optional provider-neutral video generation adapter and
  rendered asset tracking after manual prompt quality is validated.
- **[FUTURE]** Add reusable character, environment, style, voice, and music
  libraries, including 3D consistency support.
- **[FUTURE]** Add publishing and analytics only after approved content,
  rendered assets, and platform requirements are established.

See [01_PRODUCT_REQUIREMENTS.md](./01_PRODUCT_REQUIREMENTS.md) for scope,
[02_SYSTEM_ARCHITECTURE.md](./02_SYSTEM_ARCHITECTURE.md) for boundaries,
[03_DEVELOPMENT_ROADMAP.md](./03_DEVELOPMENT_ROADMAP.md) for sequencing, and
[04_BACKLOG_AND_TASKS.md](./04_BACKLOG_AND_TASKS.md) for prioritized work.

## Development constraints

Keep the implementation Python-based, locally executable, and organized as a
modular monolith. Prefer configuration, explicit contracts, small modules,
and tests over new infrastructure. Do not introduce microservices,
Kubernetes, event buses, or distributed systems for this project.


## Instagram auto-publishing setup

1. Switch the Instagram account to a **Professional** account (Creator or
   Business) in the Instagram app settings.
2. Create a Facebook account (needed only to register as a Meta developer),
   then register at developers.facebook.com and create an app.
3. Add the **Instagram** product, choose **API setup with Instagram login**,
   add the Instagram account, and generate a token with
   `instagram_business_basic` and `instagram_business_content_publish`.
4. Put `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_ACCOUNT_ID` in `.env`, then
   check the connection: `python3 -m scripts.publish_post --check`.
5. Create a Cloudflare R2 bucket with public access and fill the `R2_*`
   values in `.env` (Instagram fetches the MP4 from that public URL).
6. Optional: `python3 -m scripts.publish_scheduled --install` publishes
   scheduled Reels every minute while the Mac is on; `--uninstall` stops it.
   Long-lived tokens expire after about 60 days; extend them with
   `python3 -m scripts.publish_post --refresh-token`.
7. Optional, Facebook Page: in the same Meta app add the use case **Manage
   everything on your Page**; in Graph API Explorer generate a user token
   with `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`
   (tick the Page), extend it in the Access Token Debugger, then use it to
   fetch the Page's own token (`{page-id}?fields=access_token`; new-style
   Pages may not appear in `me/accounts`). Put `FACEBOOK_PAGE_ID` and
   `FACEBOOK_PAGE_TOKEN` in `.env`; `--check` confirms the Page. A Page token
   made from a long-lived user token does not expire. New Pages are rate
   limited by Facebook at first; the app retries such posts hours later.


## Cloud scheduler

Scheduled posts are published by a Cloudflare Worker (`cloud_scheduler/`,
free plan), so they go out on time while the Mac is asleep.

- **Schedule** in the review UI uploads the post's media to R2 and queues the
  job in the Worker; editing the caption, first comment, or sharing switches,
  or re-rendering, re-queues it; **Cancel schedule** removes it.
- Every minute the Worker publishes due posts step by step: Instagram, the
  first comment, Facebook (if `FACEBOOK_AUTO_POST=on`), Threads (if set up),
  then deletes the R2 copies. It refreshes the Instagram and Threads tokens
  weekly.
- The Mac collects results each minute while it is awake and marks posts
  Published. If the Worker cannot be reached 20 minutes after a post is due,
  the Mac publishes it instead, after checking Instagram for a copy.

Setup (once): `cd cloud_scheduler && npm install && npx wrangler login`,
`npx wrangler kv namespace create JOBS` (put the id in `wrangler.toml`),
`npx wrangler deploy`, `npx wrangler secret put SCHEDULER_SECRET`, then put
`CLOUD_SCHEDULER_URL` and `CLOUD_SCHEDULER_SECRET` in `.env` and run:

```bash
python3 -m scripts.cloud_scheduler --setup          # send tokens, check health
python3 -m scripts.cloud_scheduler --status
python3 -m scripts.cloud_scheduler --test post_035  # dry run, publishes nothing
```

Run `--setup` again after changing a token in `.env` (for example when
adding Threads). Watch the Worker live with `cd cloud_scheduler && npx wrangler tail`.

## Backups

Drafts, art, renders, history, and music are ignored by git, so they are
backed up separately to iCloud Drive (`Content_Generation_Agent backups/`),
keeping the four newest zips. The scheduler does this automatically about
once a week; run one any time with:

```bash
python3 -m scripts.backup_content
```

`.env` (tokens and keys) is never included; keep it safe separately.
