"""Instagram performance for posts made with this project.

Insights are fetched on demand (they change slowly and the API is rate
limited), cached in generated_assets/performance.json, and grouped by the
choices the generator made: story mode, visual style, and thinker.
"""

import json
import re
from datetime import datetime, timezone

from facebook_publisher import FacebookPublishError, FacebookPublisher, facebook_configured
from instagram_publisher import InstagramPublisher, InstagramPublishError
from post_storage import load_post
from project_paths import GENERATED_ASSETS_DIRECTORY, GENERATED_POSTS_DIRECTORY


CACHE_PATH = GENERATED_ASSETS_DIRECTORY / "performance.json"
_HASHTAG_PATTERN = re.compile(r"(?<![\w#])#(\w+)")
_METRICS = ("views", "reach", "saved", "shares", "total_interactions")
_GROUPS = (
    ("hashtag_count", "Hashtag count"),
    ("story_mode", "Story mode"),
    ("visual_style", "Visual style"),
    ("thinker", "Thinker"),
    ("hook_formula", "Hook formula"),
)


def _hook_formula(record):
    """The saved hook formula, or one read from an older post's hook."""
    if record.get("hook_formula"):
        return record["hook_formula"]
    try:
        from hook_score import classify, formulas_for

        formula = classify(
            re.sub(r"\*\*(.+?)\*\*", r"\1", str(record.get("main_point") or "")),
            formulas_for(record.get("profile_id")),
        )
    except Exception:  # A config problem must not break the report.
        return "unclassified"
    return formula["id"] if formula else "unclassified"


def hashtags_of(caption):
    """The caption's hashtags in order, e.g. ['#Buddhism', '#Dharma']."""
    return [f"#{tag}" for tag in _HASHTAG_PATTERN.findall(caption or "")]


def _published_records(posts_directory=GENERATED_POSTS_DIRECTORY):
    records = []
    for path in sorted(posts_directory.glob("post_*.json")):
        try:
            record = load_post(path.stem)
        except Exception:  # A broken draft must not break the report.
            continue
        if record.get("status") == "Published":
            records.append(record)
    return records


def _facebook_views(record, facebook):
    """Plays of the Reel's Facebook copy, or None when it has none."""
    video_id = record.get("facebook_video_id")
    if not facebook or not video_id:
        return None
    try:
        return int(facebook._graph("GET", video_id, fields="views").get("views", 0))
    except (FacebookPublishError, ValueError, TypeError):
        return None


def fetch_performance(publisher=None, records=None, facebook=None):
    """Return one row of metrics per published post the account still has.

    The Instagram app's view count adds the Facebook copy's views, so those
    are fetched too and summed into ``total_views``.
    """
    publisher = publisher or InstagramPublisher()
    if facebook is None and facebook_configured():
        try:
            facebook = FacebookPublisher()
        except FacebookPublishError:
            facebook = None
    base = publisher._base_url
    records = records if records is not None else _published_records()
    media = publisher._request(
        "GET",
        f"{base}/me/media",
        fields="id,permalink,media_product_type,timestamp,like_count,comments_count",
        limit=100,
    ).get("data", [])
    by_id = {item["id"]: item for item in media}
    by_link = {item.get("permalink"): item for item in media}
    rows = []
    for record in records:
        item = by_id.get(record.get("instagram_media_id")) or by_link.get(
            record.get("instagram_permalink")
        )
        if item is None:
            continue
        metrics = ",".join(_METRICS)
        if item.get("media_product_type") == "REELS":
            metrics += ",ig_reels_avg_watch_time"
        try:
            payload = publisher._request(
                "GET", f"{base}/{item['id']}/insights", metric=metrics
            )
            values = {
                entry["name"]: entry["values"][0]["value"]
                for entry in payload.get("data", [])
            }
        except InstagramPublishError:
            values = {}  # Very new posts can lack insights for a while.
        watch_ms = values.get("ig_reels_avg_watch_time")
        rows.append(
            {
                "id": record["id"],
                "title": record.get("title", ""),
                "hashtags": hashtags_of(record.get("caption")),
                "hashtag_count": f"{len(hashtags_of(record.get('caption')))} hashtags",
                "permalink": item.get("permalink"),
                "posted_at": item.get("timestamp"),
                "story_mode": record.get("subtype")
                or record.get("qa_subtype")
                or "unspecified",
                "visual_style": record.get("visual_style") or "unspecified",
                "thinker": record.get("thinker_id") or "unspecified",
                "hook_formula": _hook_formula(record),
                "likes": item.get("like_count", 0),
                "comments": item.get("comments_count", 0),
                **{name: values.get(name, 0) for name in _METRICS},
                "avg_watch_seconds": round(watch_ms / 1000, 1) if watch_ms else None,
            }
        )
        rows[-1]["facebook_views"] = _facebook_views(record, facebook)
        rows[-1]["total_views"] = rows[-1]["views"] + (rows[-1]["facebook_views"] or 0)
    return rows


def summarize(rows):
    """Average the key metrics per story mode, visual style, and thinker."""
    groups = {}
    for key, label in _GROUPS:
        buckets = {}
        for row in rows:
            buckets.setdefault(row.get(key, "unknown"), []).append(row)
        summary = []
        for value, items in buckets.items():
            watched = [r["avg_watch_seconds"] for r in items if r["avg_watch_seconds"]]
            summary.append(
                {
                    "value": value,
                    "posts": len(items),
                    "avg_views": round(
                        sum(r.get("total_views", r["views"]) for r in items) / len(items)
                    ),
                    "avg_reach": round(sum(r["reach"] for r in items) / len(items)),
                    "saves": sum(r["saved"] for r in items),
                    "shares": sum(r["shares"] for r in items),
                    "avg_watch_seconds": (
                        round(sum(watched) / len(watched), 1) if watched else None
                    ),
                }
            )
        summary.sort(key=lambda item: item["avg_views"], reverse=True)
        groups[label] = summary
    return groups


def refresh_report(publisher=None, cache_path=CACHE_PATH, records=None):
    rows = fetch_performance(publisher, records)
    report = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "posts": sorted(rows, key=lambda row: row["reach"], reverse=True),
        "groups": summarize(rows),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def cached_report(cache_path=CACHE_PATH):
    try:
        report = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # Reports saved before hashtags were added still show them.
    for row in report.get("posts", []):
        if "hashtags" not in row:
            try:
                row["hashtags"] = hashtags_of(load_post(row["id"]).get("caption"))
            except Exception:
                row["hashtags"] = []
    report["posts"] = sorted(
        report.get("posts", []), key=lambda row: row.get("reach") or 0, reverse=True
    )
    return report


# Used until there is data: evenings and early mornings suit reflective content.
DEFAULT_BEST_HOURS = (19, 7, 21)


def _hour_label(hour):
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def best_posting_hours(report=None, publisher=None, now=None):
    """Up to three good posting hours (local time) and where they come from.

    Instagram's online-followers data needs about 100 followers; until then
    the hours with the best average views of your own posts are used, and
    with fewer than three posts, sensible defaults.
    """
    try:
        publisher = publisher or InstagramPublisher()
        data = publisher._request(
            "GET", f"{publisher._base_url}/{publisher._account_id}/insights",
            metric="online_followers", period="lifetime",
        ).get("data") or []
        values = (data[0].get("values") or [{}])[-1].get("value") if data else None
    except (InstagramPublishError, IndexError, AttributeError):
        values = None
    if values:
        # Instagram reports these hours in UTC; show them in local time.
        offset = round((now or datetime.now().astimezone()).utcoffset().total_seconds() / 3600)
        ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)[:3]
        hours = [((int(hour) + offset) % 24, count) for hour, count in ranked]
        return {
            "source": "Instagram: when your followers are online",
            "hours": [{"hour": hour, "label": _hour_label(hour), "detail": f"{count} followers online"} for hour, count in hours],
        }
    posts = (report or cached_report() or {}).get("posts", [])
    by_hour = {}
    for post in posts:
        try:
            posted = datetime.strptime(post["posted_at"], "%Y-%m-%dT%H:%M:%S%z").astimezone()
        except (KeyError, TypeError, ValueError):
            continue
        by_hour.setdefault(posted.hour, []).append(post.get("total_views") or post.get("views") or 0)
    if sum(len(items) for items in by_hour.values()) >= 3:
        ranked = sorted(by_hour.items(), key=lambda item: sum(item[1]) / len(item[1]), reverse=True)[:3]
        return {
            "source": f"Your posts so far ({sum(len(v) for v in by_hour.values())} posts; Instagram's audience data needs about 100 followers)",
            "hours": [{"hour": hour, "label": _hour_label(hour),
                       "detail": f"avg {round(sum(views) / len(views))} views over {len(views)} post(s)"}
                      for hour, views in ranked],
        }
    return {
        "source": "Suggested defaults (not enough data yet)",
        "hours": [{"hour": hour, "label": _hour_label(hour), "detail": ""} for hour in DEFAULT_BEST_HOURS],
    }
