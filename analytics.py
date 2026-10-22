"""Instagram performance for posts made with this project.

Insights are fetched on demand (they change slowly and the API is rate
limited), cached in generated_assets/performance.json, and grouped by the
choices the generator made: story mode, visual style, and thinker.
"""

import json
from datetime import datetime, timezone

from instagram_publisher import InstagramPublisher, InstagramPublishError
from post_storage import load_post
from project_paths import GENERATED_ASSETS_DIRECTORY, GENERATED_POSTS_DIRECTORY


CACHE_PATH = GENERATED_ASSETS_DIRECTORY / "performance.json"
_METRICS = ("views", "reach", "saved", "shares", "total_interactions")
_GROUPS = (
    ("story_mode", "Story mode"),
    ("visual_style", "Visual style"),
    ("thinker", "Thinker"),
)


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


def fetch_performance(publisher=None, records=None):
    """Return one row of metrics per published post the account still has."""
    publisher = publisher or InstagramPublisher()
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
                "permalink": item.get("permalink"),
                "posted_at": item.get("timestamp"),
                "story_mode": record.get("qa_subtype") or "unspecified",
                "visual_style": record.get("visual_style") or "unspecified",
                "thinker": record.get("thinker_id") or "unspecified",
                "likes": item.get("like_count", 0),
                "comments": item.get("comments_count", 0),
                **{name: values.get(name, 0) for name in _METRICS},
                "avg_watch_seconds": round(watch_ms / 1000, 1) if watch_ms else None,
            }
        )
    return rows


def summarize(rows):
    """Average the key metrics per story mode, visual style, and thinker."""
    groups = {}
    for key, label in _GROUPS:
        buckets = {}
        for row in rows:
            buckets.setdefault(row[key], []).append(row)
        summary = []
        for value, items in buckets.items():
            watched = [r["avg_watch_seconds"] for r in items if r["avg_watch_seconds"]]
            summary.append(
                {
                    "value": value,
                    "posts": len(items),
                    "avg_views": round(sum(r["views"] for r in items) / len(items)),
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
        "posts": sorted(rows, key=lambda row: row["views"], reverse=True),
        "groups": summarize(rows),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def cached_report(cache_path=CACHE_PATH):
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
