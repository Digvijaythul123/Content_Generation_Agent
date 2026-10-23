from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import quote

from ai_service import AIServiceError
from config_loader import (
    ConfigurationError,
    load_comedy_config,
    load_brand,
    load_format,
    load_platform,
    load_profile_config,
    load_profile_subtypes,
    load_focus_thinkers,
    load_profile_thinkers,
    load_profile_visual_styles,
)
from content_agent import simplify_copy
from content_models import ContentValidationError, validate_instagram_caption
from instagram_publisher import InstagramPublishError, InstagramPublisher
from media_host import MediaHostError, R2MediaHost
from art_generator import (
    MAX_ARTWORK_BYTES,
    MAX_VIDEO_ARTWORK_BYTES,
    VIDEO_ARTWORK_SUFFIXES,
    ArtGenerationError,
    artwork_path,
    build_art_prompt,
    generate_post_artwork,
    is_designed,
    save_post_artwork,
)
from content_text import strip_highlights
from media_renderer import (
    MediaRenderError,
    layout_for,
    post_image_path,
    render_post_image,
)
from content_pipeline import generate_content
from analytics import cached_report, refresh_report
from music_library import SILENT, list_tracks
from video_renderer import VIDEO_EFFECTS, reel_video_path, render_image_reel_video
from post_prompt import build_post_prompt_file
from post_storage import (
    PostStorageError,
    create_post,
    load_post,
    save_post,
)
from app_settings import get_setting
from project_paths import (
    PROJECT_ROOT,
    CONFIG_DIRECTORY,
    GENERATED_ASSETS_DIRECTORY,
    GENERATED_IMAGES_DIRECTORY,
    GENERATED_POSTS_DIRECTORY,
    GENERATED_REELS_DIRECTORY,
    GENERATED_VIDEOS_DIRECTORY,
)
from reel_storage import (
    ReelStorageError,
    create_reel,
    load_reel,
    save_reel,
)
from scripts.image_prompt_generator import generate_image_prompts
from scripts.storyboard_generator import (
    StoryboardValidationError,
    generate_storyboard,
)
from scripts.video_prompt_generator import generate_master_prompt


UI_FILE = Path(__file__).with_name("review_ui.html")
_CONTENT_DIRECTORIES = {
    "reel": GENERATED_REELS_DIRECTORY,
    "post": GENERATED_POSTS_DIRECTORY,
}
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_REQUEST_BYTES = 64 * 1024
_HISTORY_LOCK = threading.Lock()
_STAGE_LOCK = threading.Lock()
_ACTIVE_STAGES = set()
_STAGE_ACTION_ERRORS = (
    AIServiceError,
    ConfigurationError,
    PostStorageError,
    ReelStorageError,
    StoryboardValidationError,
    MediaRenderError,
    ArtGenerationError,
    MediaHostError,
    InstagramPublishError,
    ContentValidationError,
    OSError,
    ValueError,
)


class ReviewUIError(RuntimeError):
    """Raised when saved content cannot be read by the review UI."""


class PartialGenerationError(ValueError):
    """Raised when a batch stops after one or more drafts were saved."""


def _read_record(path, content_type):
    try:
        with path.open(encoding="utf-8") as content_file:
            record = json.load(content_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewUIError(
            f"Could not read {content_type} record {path}: {error}"
        ) from error
    if not isinstance(record, dict):
        raise ReviewUIError(
            f"Content record {path} must contain a JSON object."
        )
    return record


def list_content_items():
    items = []
    for content_type, directory in _CONTENT_DIRECTORIES.items():
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            record = _read_record(path, content_type)
            content_id = record.get("id", path.stem)
            if not isinstance(content_id, str) or not _ID_PATTERN.fullmatch(
                content_id
            ):
                raise ReviewUIError(f"Content record {path} has an invalid ID.")
            title = record.get("title", "")
            status = record.get("status", "UNKNOWN")
            if not isinstance(title, str) or not isinstance(status, str):
                raise ReviewUIError(
                    f"Content record {path} has invalid title or status."
                )
            items.append(
                {
                    "id": content_id,
                    "type": content_type,
                    "title": title.strip() or "Untitled",
                    "status": status.strip() or "UNKNOWN",
                    "brand_id": record.get("brand_id") or "",
                    "profile_id": record.get("profile_id", ""),
                    "category_id": record.get("category_id", ""),
                    "comedy_subtype": record.get("comedy_subtype", ""),
                    "subtype": record.get("subtype") or record.get("qa_subtype", ""),
                    "thinker_id": record.get("thinker_id", ""),
                    "visual_style": record.get("visual_style", ""),
                    "scheduled_at": record.get("scheduled_at") or "",
                    "schedule_failed": bool(record.get("schedule_failed")),
                    "schedule_retrying": bool(record.get("schedule_retry_at")),
                    "format_id": record.get(
                        "format_id", "reel" if content_type == "reel" else ""
                    ),
                    "platform_id": record.get("platform_id", ""),
                    "search_text": " ".join(
                        value
                        for key, value in record.items()
                        if key != "raw_content" and isinstance(value, str)
                    ),
                }
            )

    def sort_key(item):
        identifier = item["id"].rsplit("_", 1)
        suffix = identifier[-1]
        return identifier[0], int(suffix) if suffix.isdigit() else -1

    return sorted(items, key=sort_key, reverse=True)


def get_content_item(content_type, content_id):
    if content_type not in _CONTENT_DIRECTORIES:
        raise KeyError(f"Unknown content type: {content_type}")
    if not isinstance(content_id, str) or not _ID_PATTERN.fullmatch(content_id):
        raise KeyError(f"Invalid content ID: {content_id!r}")

    directory = _CONTENT_DIRECTORIES[content_type]
    for path in directory.glob("*.json") if directory.exists() else ():
        record = _read_record(path, content_type)
        if record.get("id", path.stem) == content_id:
            return record
    raise KeyError(f"{content_type.title()} not found: {content_id}")


def _history_path(content_id):
    return GENERATED_ASSETS_DIRECTORY / f"{content_id}_history.jsonl"


def _append_history(content_type, content_id, event, **details):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_type": content_type,
        "content_id": content_id,
        "event": event,
        **details,
    }
    path = _history_path(content_id)
    try:
        GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with _HISTORY_LOCK, path.open("a", encoding="utf-8") as history_file:
            history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            history_file.flush()
    except OSError as error:
        raise ReviewUIError(
            f"Could not record activity for {content_id}: {error}"
        ) from error
    return entry


def get_history(content_type, content_id):
    get_content_item(content_type, content_id)
    path = _history_path(content_id)
    if not path.is_file():
        return []
    entries = []
    try:
        with path.open(encoding="utf-8") as history_file:
            for line_number, line in enumerate(history_file, start=1):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ReviewUIError(
                        f"Invalid history entry in {path} at line "
                        f"{line_number}: {error}"
                    ) from error
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError as error:
        raise ReviewUIError(
            f"Could not read activity history {path}: {error}"
        ) from error
    return list(reversed(entries))


def get_recent_activity(limit=12):
    entries = []
    if not GENERATED_ASSETS_DIRECTORY.exists():
        return entries
    for path in GENERATED_ASSETS_DIRECTORY.glob("*_history.jsonl"):
        content_id = path.name[: -len("_history.jsonl")]
        try:
            with path.open(encoding="utf-8") as history_file:
                for line_number, line in enumerate(history_file, start=1):
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ReviewUIError(
                            f"Invalid history entry in {path} at line "
                            f"{line_number}: {error}"
                        ) from error
                    if isinstance(entry, dict):
                        entry.setdefault("content_id", content_id)
                        entries.append(entry)
        except OSError as error:
            raise ReviewUIError(
                f"Could not read activity history {path}: {error}"
            ) from error
    return sorted(
        entries,
        key=lambda entry: entry.get("timestamp", ""),
        reverse=True,
    )[:limit]


def _is_instagram_post(record):
    return str(record.get("platform_id") or "").startswith("instagram") and (
        record.get("format_id", "single_page") == "single_page"
    )


def _is_image_reel(record):
    return record.get("format_id") == "image_reel"


def _post_brand(record):
    brand_id = record.get("brand_id")
    if not brand_id:
        return None
    try:
        return load_brand(brand_id)
    except ConfigurationError:
        return None


def _needs_artwork(record):
    return _is_image_reel(record) or (
        _is_instagram_post(record)
        and (
            record.get("layout") == "poster"
            or layout_for(_post_brand(record)) == "quote_painting"
        )
    )


def _artwork_output(content_id):
    return artwork_path(content_id) or (
        GENERATED_ASSETS_DIRECTORY / f"{content_id}_art.png"
    )


def _asset_paths(content_type, content_id):
    if content_type == "post":
        return [
            (
                "design_prompt",
                "Design prompt",
                "Image prompt",
                GENERATED_ASSETS_DIRECTORY
                / f"{content_id}_design_prompt.txt",
            ),
            (
                "artwork",
                "Background artwork",
                "Generated image",
                _artwork_output(content_id),
            ),
            (
                "instagram_image",
                "Instagram image",
                "Generated image",
                post_image_path(content_id),
            ),
            (
                "reel_video",
                "Reel video",
                "Generated video",
                reel_video_path(content_id),
            ),
        ]
    if content_type != "reel":
        raise KeyError(f"Unknown content type: {content_type}")

    paths = [
        (
            "storyboard",
            "Storyboard",
            "Storyboard",
            GENERATED_VIDEOS_DIRECTORY / f"{content_id}_storyboard.json",
        ),
        (
            "scene_plan",
            "Scene plan",
            "Scene file",
            GENERATED_VIDEOS_DIRECTORY / f"{content_id}_scenes.txt",
        ),
        (
            "image_prompts",
            "Image prompts",
            "Image prompts",
            GENERATED_IMAGES_DIRECTORY / f"{content_id}_image_prompts.txt",
        ),
        (
            "video_prompt",
            "Master video prompt",
            "Video prompt",
            GENERATED_VIDEOS_DIRECTORY / f"{content_id}_master_prompt.txt",
        ),
    ]
    legacy_image_prompts = (
        GENERATED_VIDEOS_DIRECTORY / f"{content_id}_image_prompts.txt"
    )
    if not paths[2][3].is_file() and legacy_image_prompts.is_file():
        paths[2] = (
            "image_prompts",
            "Image prompts",
            "Image prompts",
            legacy_image_prompts,
        )
    image_directory = GENERATED_IMAGES_DIRECTORY / content_id
    if image_directory.is_dir():
        for index, path in enumerate(sorted(image_directory.glob("*")), start=1):
            if path.is_file():
                paths.append(
                    (
                        f"generated_image_{index}",
                        path.name,
                        "Generated image",
                        path,
                    )
                )
    image_files = sorted(
        path
        for path in GENERATED_IMAGES_DIRECTORY.glob(f"{content_id}_*")
        if path.is_file()
        and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")
    )
    for index, path in enumerate(image_files, start=1):
        paths.append(
            (
                f"generated_image_file_{index}",
                path.name,
                "Generated image",
                path,
            )
        )
    video_directory = GENERATED_VIDEOS_DIRECTORY / content_id
    if video_directory.is_dir():
        for index, path in enumerate(sorted(video_directory.glob("*")), start=1):
            if path.is_file():
                paths.append(
                    (
                        f"generated_video_{index}",
                        path.name,
                        "Generated video",
                        path,
                    )
                )
    video_files = sorted(
        path
        for path in GENERATED_VIDEOS_DIRECTORY.glob(f"{content_id}_*")
        if path.is_file()
        and path.suffix.lower() in (".mp4", ".mov", ".webm", ".m4v")
    )
    for index, path in enumerate(video_files, start=1):
        paths.append(
            (
                f"generated_video_file_{index}",
                path.name,
                "Generated video",
                path,
            )
        )
    return paths


def list_assets(content_type, content_id):
    get_content_item(content_type, content_id)
    return [
        {
            "key": key,
            "name": name,
            "type": asset_type,
            "url": f"/api/assets/{content_type}/{content_id}/{key}",
        }
        for key, name, asset_type, path in _asset_paths(
            content_type, content_id
        )
        if path.is_file()
    ]


def read_asset(content_type, content_id, asset_key):
    get_content_item(content_type, content_id)
    for key, name, asset_type, path in _asset_paths(
        content_type, content_id
    ):
        if key == asset_key and path.is_file():
            try:
                return path.name, asset_type, path.read_bytes()
            except OSError as error:
                raise ReviewUIError(
                    f"Could not read asset {path}: {error}"
                ) from error
    raise KeyError(f"Asset not found: {asset_key}")


def _stage_output_paths(content_type, content_id, record=None):
    if content_type == "post":
        paths = {}
        if record is None or "design_prompt" in record:
            paths["design_prompt"] = (
                GENERATED_ASSETS_DIRECTORY / f"{content_id}_design_prompt.txt"
            )
        if record is None or _needs_artwork(record):
            paths["artwork"] = _artwork_output(content_id)
        if record is None or _is_instagram_post(record) or _is_image_reel(record):
            paths["instagram_image"] = post_image_path(content_id)
        if record is None or _is_image_reel(record):
            paths["reel_video"] = reel_video_path(content_id)
        return paths
    image_prompts = GENERATED_IMAGES_DIRECTORY / f"{content_id}_image_prompts.txt"
    legacy_image_prompts = (
        GENERATED_VIDEOS_DIRECTORY / f"{content_id}_image_prompts.txt"
    )
    if not image_prompts.is_file() and legacy_image_prompts.is_file():
        image_prompts = legacy_image_prompts
    return {
        "storyboard": GENERATED_VIDEOS_DIRECTORY
        / f"{content_id}_storyboard.json",
        "scene_plan": GENERATED_VIDEOS_DIRECTORY
        / f"{content_id}_scenes.txt",
        "image_prompts": image_prompts,
        "video_prompt": GENERATED_VIDEOS_DIRECTORY
        / f"{content_id}_master_prompt.txt",
    }


def get_pipeline(content_type, content_id):
    record = get_content_item(content_type, content_id)
    files = _stage_output_paths(content_type, content_id, record)
    history = get_history(content_type, content_id)
    last_stage_events = {}
    for event in history:
        stage = event.get("stage")
        if stage and stage not in last_stage_events:
            last_stage_events[stage] = event

    common = [
        {
            "id": "content",
            "label": "Content generated",
            "status": "ready",
            "available": True,
        },
        {
            "id": "review",
            "label": "Reviewed",
            "status": (
                "ready"
                if record.get("status") in ("Approved", "Rejected", "Published")
                else "not_started"
            ),
            "available": True,
        },
        {
            "id": "approval",
            "label": "Approved",
            "status": (
                "ready"
                if record.get("status") in ("Approved", "Published")
                else (
                    "rejected"
                    if record.get("status") == "Rejected"
                    else "not_started"
                )
            ),
            "available": True,
        },
    ]
    production = (
        (
            ([("design_prompt", "Design prompt")] if "design_prompt" in record else [])
            + ([("artwork", "Artwork")] if _needs_artwork(record) else [])
            + (
                [("instagram_image", "Instagram image")]
                if _is_instagram_post(record) or _is_image_reel(record)
                else []
            )
            + ([("reel_video", "Reel video")] if _is_image_reel(record) else [])
        )
        if content_type == "post"
        else [
            ("storyboard", "Storyboard"),
            ("scene_plan", "Scene plan"),
            ("image_prompts", "Image prompts"),
            ("video_prompt", "Video prompt"),
        ]
    )
    for stage, label in production:
        output = files[stage]
        needs_art_first = (
            stage in ("instagram_image", "reel_video")
            and "artwork" in files
            and not files["artwork"].is_file()
        )
        last_event = last_stage_events.get(stage)
        stage_key = (content_type, content_id, stage)
        if last_event and last_event.get("event") == "stage_started":
            with _STAGE_LOCK:
                status = (
                    "running"
                    if stage_key in _ACTIVE_STAGES
                    else "failed"
                )
        elif last_event and last_event.get("event") == "stage_failed":
            status = "failed"
        elif output.is_file():
            status = "ready"
        elif record.get("status") == "Published":
            status = "not_applicable"
        elif record.get("status") != "Approved":
            status = "blocked"
        else:
            status = "not_started"
        common.append(
            {
                "id": stage,
                "label": label,
                "status": status,
                "available": True,
                "can_run": (
                    record.get("status") == "Approved"
                    and not needs_art_first
                    and not (
                        content_type == "reel"
                        and stage == "image_prompts"
                        and not (
                            files["storyboard"].is_file()
                            or files["scene_plan"].is_file()
                        )
                    )
                    and not (
                        content_type == "reel"
                        and stage == "video_prompt"
                        and not files["image_prompts"].is_file()
                    )
                ),
                "reason": (
                    "Generate the artwork first."
                    if needs_art_first and record.get("status") == "Approved"
                    else "Generate a storyboard first."
                    if content_type == "reel"
                    and stage == "image_prompts"
                    and not (
                        files["storyboard"].is_file()
                        or files["scene_plan"].is_file()
                    )
                    else (
                        "Generate image prompts first."
                        if content_type == "reel"
                        and stage == "video_prompt"
                        and not files["image_prompts"].is_file()
                        else (
                            "Approve this content before production."
                            if record.get("status") != "Approved"
                            else ""
                        )
                    )
                ),
            }
        )
    common.extend(
        ([] if _is_image_reel(record) else [
            {
                "id": "video",
                "label": "Video generated",
                "status": "not_applicable" if content_type == "post" else "future",
                "available": False,
                "reason": (
                    "Video generation does not apply to post formats."
                    if content_type == "post"
                    else "Video rendering is not integrated yet."
                ),
            },
        ])
        + [_publishing_stage(content_type, content_id, record, files, last_stage_events)]
    )
    return {"stages": common}


def _publishing_stage(content_type, content_id, record, files, last_stage_events):
    if content_type == "post" and _is_image_reel(record):
        published = record.get("status") == "Published"
        video_ready = files["reel_video"].is_file()
        if published:
            reason = "Posted to Instagram."
        elif record.get("status") != "Approved":
            reason = "Approve this content first."
        elif not video_ready:
            reason = "Render the Reel video first."
        else:
            reason = ""
        return {
            "id": "publishing",
            "label": "Published",
            "status": "ready" if published else (
                "not_started" if video_ready and record.get("status") == "Approved"
                else "blocked"
            ),
            "available": True,
            "can_run": not published
            and record.get("status") == "Approved"
            and video_ready,
            "manual": True,
            "reason": reason,
            "permalink": record.get("instagram_permalink"),
            "scheduled_at": record.get("scheduled_at"),
            "schedule_failed": record.get("schedule_failed"),
            "schedule_retry_at": record.get("schedule_retry_at"),
            "schedule_last_error": record.get("schedule_last_error"),
            "connection": publishing_connection(),
        }
    if content_type != "post" or not _is_instagram_post(record):
        return {
            "id": "publishing",
            "label": "Published",
            "status": "future",
            "available": False,
            "reason": "Publishing is available for Instagram Feed posts only.",
        }
    last_event = last_stage_events.get("publishing")
    with _STAGE_LOCK:
        running = (content_type, content_id, "publishing") in _ACTIVE_STAGES
    image_ready = files["instagram_image"].is_file()
    if record.get("status") == "Published":
        status = "ready"
    elif running:
        status = "running"
    elif last_event and last_event.get("event") in ("stage_failed", "stage_started"):
        status = "failed"
    elif record.get("status") != "Approved":
        status = "blocked"
    else:
        status = "not_started"
    if record.get("status") == "Published":
        reason = "Already published to Instagram."
    elif record.get("status") != "Approved":
        reason = "Approve this content before publishing."
    elif not image_ready:
        reason = "Render the Instagram image and review it first."
    else:
        reason = ""
    return {
        "id": "publishing",
        "label": "Published",
        "status": status,
        "available": True,
        "can_run": not reason and not running,
        "reason": reason,
        "permalink": record.get("instagram_permalink"),
    }


def get_dashboard_summary():
    items = list_content_items()
    counts = {
        "total": len(items),
        "drafts": sum(item["status"] == "Draft" for item in items),
        "approved": sum(item["status"] == "Approved" for item in items),
        "rejected": sum(item["status"] == "Rejected" for item in items),
        "published": sum(item["status"] == "Published" for item in items),
        "ready_for_production": 0,
        "failed_stages": 0,
    }
    for item in items:
        stages = get_pipeline(item["type"], item["id"])["stages"]
        if item["type"] == "post":
            post = get_content_item("post", item["id"])
            ready = (
                any(
                    stage["id"] == "design_prompt"
                    and stage["status"] == "ready"
                    for stage in stages
                )
                if "design_prompt" in post
                else True
            )
        else:
            ready = any(
                stage["id"] == "video_prompt" and stage["status"] == "ready"
                for stage in stages
            )
        counts["ready_for_production"] += int(
            item["status"] == "Approved" and ready
        )
        counts["failed_stages"] += sum(
            stage["status"] == "failed" for stage in stages
        )
    return counts


def review_content(content_type, content_id, decision, reason=""):
    if decision not in ("Approved", "Rejected"):
        raise ValueError("Review decision must be Approved or Rejected.")
    if not isinstance(reason, str):
        raise ValueError("Review reason must be text.")
    if content_type == "reel":
        record = load_reel(content_id)
        save = save_reel
    elif content_type == "post":
        record = load_post(content_id)
        save = save_post
    else:
        raise KeyError(f"Unknown content type: {content_type}")
    if record.get("status", "Draft") != "Draft":
        raise ValueError("Only Draft content can be approved or rejected.")
    record["status"] = decision
    save(content_id, record)
    _append_history(
        content_type,
        content_id,
        "review_decision",
        decision=decision,
        reason=reason.strip(),
    )
    return record


def run_production_stage(content_type, content_id, stage):
    record = get_content_item(content_type, content_id)
    if record.get("status") != "Approved":
        raise ValueError("Production stages require Approved content.")
    if stage not in _stage_output_paths(content_type, content_id, record):
        raise ValueError(f"Stage is not supported for {content_type}: {stage}")
    output_paths = _stage_output_paths(content_type, content_id, record)
    if content_type == "reel" and stage == "image_prompts":
        if not (
            output_paths["storyboard"].is_file()
            or output_paths["scene_plan"].is_file()
        ):
            raise ValueError("Generate the storyboard before image prompts.")
    if content_type == "reel" and stage == "video_prompt":
        if not output_paths["image_prompts"].is_file():
            raise ValueError("Generate image prompts before the video prompt.")
    stage_key = (content_type, content_id, stage)
    with _STAGE_LOCK:
        if stage_key in _ACTIVE_STAGES:
            raise ValueError("This production stage is already running.")
        _ACTIVE_STAGES.add(stage_key)
    try:
        _append_history(content_type, content_id, "stage_started", stage=stage)
        if content_type == "reel":
            if stage in ("storyboard", "scene_plan"):
                output = generate_storyboard(content_id)
            elif stage == "image_prompts":
                output = generate_image_prompts(content_id)
            else:
                output = generate_master_prompt(content_id)
        elif stage == "artwork":
            brand = _post_brand(record)
            output = generate_post_artwork(
                content_id, art_style=brand.template.art_style if brand else None
            )
            # A new painting makes the previous renders stale.
            post_image_path(content_id).unlink(missing_ok=True)
            reel_video_path(content_id).unlink(missing_ok=True)
        elif stage == "instagram_image":
            if "artwork" in output_paths and not artwork_path(content_id):
                raise ValueError("Generate the artwork before rendering the image.")
            output = render_post_image(content_id)
        elif stage == "reel_video":
            if not artwork_path(content_id):
                raise ValueError("Generate the artwork before rendering the video.")
            output = render_image_reel_video(content_id)
        else:
            format_id = record.get("format_id", "single_page")
            platform_id = record.get("platform_id", "instagram_feed")
            if stage != "design_prompt":
                raise ValueError(
                    f"Stage is not supported for {content_type}: {stage}"
                )
            brand = _post_brand(record)
            prompt = build_post_prompt_file(
                record,
                load_format(format_id),
                load_platform(platform_id),
                record.get("category_id"),
                brand.template.art_style if brand else None,
            )
            output = output_paths[stage]
            GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
            output.write_text(prompt + "\n", encoding="utf-8")
        _append_history(
            content_type,
            content_id,
            "stage_ready",
            stage=stage,
            output=str(output),
        )
        return {"stage": stage, "status": "ready"}
    except _STAGE_ACTION_ERRORS as error:
        _append_history(
            content_type,
            content_id,
            "stage_failed",
            stage=stage,
            error=str(error),
        )
        raise
    finally:
        with _STAGE_LOCK:
            _ACTIVE_STAGES.discard(stage_key)


def _artwork_record(content_type, content_id):
    if content_type != "post":
        raise ValueError("Artwork applies to single-page posts only.")
    record = load_post(content_id)
    if not _needs_artwork(record):
        raise ValueError("This post's brand layout does not use background artwork.")
    return record


def get_art_prompt(content_type, content_id):
    """Return the text-free art prompt to paste into an image tool by hand."""
    record = _artwork_record(content_type, content_id)
    brand = _post_brand(record)
    return build_art_prompt(record, brand.template.art_style if brand else None)


def upload_artwork(content_type, content_id, image_bytes):
    """Store artwork made outside the app (e.g. the Gemini app) for a post."""
    record = _artwork_record(content_type, content_id)
    if record.get("status") != "Approved":
        raise ValueError("Approve this content before adding artwork.")
    output = save_post_artwork(content_id, image_bytes)
    post_image_path(content_id).unlink(missing_ok=True)
    reel_video_path(content_id).unlink(missing_ok=True)
    _append_history(
        content_type, content_id, "stage_ready",
        stage="artwork", source="upload", output=str(output),
    )
    return {"stage": "artwork", "status": "ready"}


_IMPORTABLE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov")


def _import_size_limit(path):
    return (
        MAX_VIDEO_ARTWORK_BYTES
        if path.suffix.lower() in VIDEO_ARTWORK_SUFFIXES
        else MAX_ARTWORK_BYTES
    )


def _import_directories():
    """Folders offered for picking artwork without a browser file dialog."""
    configured = get_setting("ARTWORK_IMPORT_DIRS")
    if configured:
        candidates = [Path(item).expanduser() for item in configured.split(os.pathsep)]
    else:
        candidates = [Path.home() / "Downloads", PROJECT_ROOT / "creative_assets"]
    return [path for path in candidates if path.is_dir()]


def list_importable_images(limit=12):
    """Return the most recent images in the import folders, newest first."""
    found = []
    for index, directory in enumerate(_import_directories()):
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if not (
                    path.is_file()
                    and path.suffix.lower() in _IMPORTABLE_SUFFIXES
                    and path.stat().st_size <= _import_size_limit(path)
                ):
                    continue
                modified = path.stat().st_mtime
            except OSError:
                continue
            found.append((modified, index, directory, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": f"{index}:{path.name}",
            "name": path.name,
            "folder": directory.name,
            "modified": datetime.fromtimestamp(modified, timezone.utc).isoformat(),
            "url": "/api/artwork_sources/" + quote(f"{index}:{path.name}", safe=""),
        }
        for modified, index, directory, path in found[:limit]
    ]


def _importable_image_path(image_id):
    index_text, separator, name = str(image_id).partition(":")
    directories = _import_directories()
    if (
        not separator
        or not index_text.isdigit()
        or int(index_text) >= len(directories)
        or not name
        or name != Path(name).name
        or name.startswith(".")
    ):
        raise KeyError(f"Image not found: {image_id}")
    path = directories[int(index_text)] / name
    if not path.is_file() or path.suffix.lower() not in _IMPORTABLE_SUFFIXES:
        raise KeyError(f"Image not found: {image_id}")
    return path


def import_artwork(content_type, content_id, image_id):
    """Attach a recent image from an import folder as the post's artwork."""
    path = _importable_image_path(image_id)
    try:
        image_bytes = path.read_bytes()
    except OSError as error:
        raise ReviewUIError(f"Could not read {path.name}: {error}") from error
    return upload_artwork(content_type, content_id, image_bytes)


# The Reel cover frame: after every line of text has faded in.
REEL_COVER_OFFSET_MS = 5000


def publishing_connection():
    """Report which publishing settings exist (not whether they are valid)."""
    return {
        "instagram": bool(
            get_setting("INSTAGRAM_ACCESS_TOKEN")
            and get_setting("INSTAGRAM_ACCOUNT_ID")
        ),
        "media_host": all(
            get_setting(name)
            for name in (
                "R2_ACCOUNT_ID",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET",
                "R2_PUBLIC_BASE_URL",
            )
        ),
    }


def _parse_schedule(value):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("The schedule must be a date and time.") from error
    if moment.tzinfo is None:
        raise ValueError("The schedule must include a timezone.")
    return moment.astimezone(timezone.utc)


# The words drawn on the image; editable until the post is published.
ON_IMAGE_TEXT_FIELDS = ("title", "main_point", "supporting_copy")


def update_post_settings(content_id, payload):
    """Save review-screen changes: caption, music track, and schedule."""
    record = load_post(content_id)
    if not _is_image_reel(record):
        # Feed posts only have a layout choice; music and schedules are Reels.
        if not _is_instagram_post(record) or set(payload) - (
            {"layout", "caption"} | set(ON_IMAGE_TEXT_FIELDS)
        ):
            raise ValueError(
                "Only the layout, caption, and on-image text can be changed for feed posts."
            )
    if record.get("status") == "Published":
        raise ValueError("This Reel is already published.")
    changed = []
    if "caption" in payload:
        caption = payload["caption"]
        if not isinstance(caption, str):
            raise ValueError("The caption must be text.")
        validate_instagram_caption(strip_highlights(caption))
        record["caption"] = caption.strip()
        changed.append("caption")
    for field in ON_IMAGE_TEXT_FIELDS:
        if field not in payload:
            continue
        text = payload[field]
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"The {field.replace('_', ' ')} cannot be empty.")
        record[field] = text.strip()
        # The renders show the old words, so render them again.
        post_image_path(content_id).unlink(missing_ok=True)
        reel_video_path(content_id).unlink(missing_ok=True)
        changed.append(field)
    if "music_track" in payload:
        track = payload["music_track"] or None
        names = {path.name for path in list_tracks()}
        if track not in (None, SILENT) and track not in names:
            raise ValueError(f"Music track {track!r} is not in the music folder.")
        if track:
            record["music_track"] = track
        else:
            record.pop("music_track", None)
        # The rendered video carries the old audio, so render it again.
        reel_video_path(content_id).unlink(missing_ok=True)
        changed.append("music_track")
    if "layout" in payload:
        if payload["layout"] not in ("poster", "panel"):
            raise ValueError("Layout must be 'poster' or 'panel'.")
        record["layout"] = payload["layout"]
        # Renders show the old layout, so render them again.
        post_image_path(content_id).unlink(missing_ok=True)
        reel_video_path(content_id).unlink(missing_ok=True)
        changed.append("layout")
    if "sparks" in payload:
        if not isinstance(payload["sparks"], bool):
            raise ValueError("Sparks must be on or off.")
        record["sparks"] = payload["sparks"]
        # The rendered video carries the old effect, so render it again.
        reel_video_path(content_id).unlink(missing_ok=True)
        changed.append("sparks")
    if "effect" in payload:
        effect = payload["effect"] or None
        if effect is not None and effect not in VIDEO_EFFECTS:
            raise ValueError(
                "Effect must be one of: " + ", ".join(VIDEO_EFFECTS) + ", or none."
            )
        record["effect"] = effect
        record.pop("sparks", None)
        # The rendered video carries the old effect, so render it again.
        reel_video_path(content_id).unlink(missing_ok=True)
        changed.append("effect")
    if "scheduled_at" in payload:
        value = payload["scheduled_at"]
        if value:
            if record.get("status") != "Approved":
                raise ValueError("Approve this Reel before scheduling it.")
            moment = _parse_schedule(value)
            if moment <= datetime.now(timezone.utc):
                raise ValueError("Choose a time in the future.")
            record["scheduled_at"] = moment.isoformat()
        else:
            record.pop("scheduled_at", None)
        for key in ("schedule_failed", "schedule_attempts",
                    "schedule_retry_at", "schedule_last_error"):
            record.pop(key, None)
        changed.append("scheduled_at")
    save_post(content_id, record)
    if is_designed(record) and set(changed) & set(ON_IMAGE_TEXT_FIELDS):
        # The image tool draws these words, so its prompt must carry the new ones.
        _write_art_prompt(content_id, record)
    _append_history(
        "post", content_id, "settings_updated", fields=changed,
        scheduled_at=record.get("scheduled_at"),
    )
    return record


def simplify_post_text(content_id, fresh=False):
    """Suggest plain-English on-image text and caption for review (not saved)."""
    record = load_post(content_id)
    if record.get("status") == "Published":
        raise ValueError("This post is published; its text cannot be changed.")
    suggestion = simplify_copy(record, fresh=fresh)
    _append_history("post", content_id, "text_suggested", fresh=fresh)
    return suggestion


def _write_art_prompt(content_id, record):
    """Rebuild the saved art prompt after the post's text or format changed."""
    if not record.get("design_prompt"):
        return
    brand = _post_brand(record)
    prompt = build_post_prompt_file(
        record,
        load_format(record.get("format_id") or "single_page"),
        load_platform(record.get("platform_id") or "instagram"),
        record.get("category_id"),
        brand.template.art_style if brand else None,
    )
    GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (GENERATED_ASSETS_DIRECTORY / f"{content_id}_design_prompt.txt").write_text(
        prompt + "\n", encoding="utf-8"
    )


def convert_to_reel(content_id):
    """Turn an unpublished feed post into a one-image Reel (video and music).

    The copy and caption carry over; the 4:5 artwork is kept but usually
    needs replacing with 9:16 art, and the art prompt is rewritten for it.
    """
    record = load_post(content_id)
    if not _is_instagram_post(record):
        raise ValueError("Only Instagram feed posts can be converted to a Reel.")
    if record.get("status") == "Published":
        raise ValueError("This post is published; it cannot be converted.")
    record.update(format_id="image_reel", platform_id="instagram", layout="poster")
    record.setdefault("music_cue", "Slow, reflective flute with a soft ambient drone.")
    save_post(content_id, record)
    post_image_path(content_id).unlink(missing_ok=True)
    _write_art_prompt(content_id, record)
    _append_history("post", content_id, "converted_to_reel")
    return record


# Network failures (a Mac waking from sleep, a slow connection) are retried
# after these waits, in minutes; other failures stop at once.
SCHEDULE_RETRY_MINUTES = (5, 10, 15, 20, 25)


def _is_transient(error):
    if isinstance(error, InstagramPublishError):
        return error.transient
    if isinstance(error, MediaHostError):
        try:
            from botocore.exceptions import BotoCoreError
        except ImportError:
            return False
        return isinstance(error.__cause__, BotoCoreError)
    return False


def _published_copy(record, publisher, since):
    """Find this post on Instagram if an earlier attempt timed out after
    Instagram had already published it, so a retry never posts twice."""
    caption = strip_highlights(record.get("caption") or "").strip()[:80]
    if not caption:
        return None
    for media in publisher.recent_media():
        try:
            posted = datetime.strptime(media["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        except (KeyError, ValueError):
            continue
        if posted >= since and (media.get("caption") or "").strip().startswith(caption):
            return media
    return None


def publish_due_posts(now=None, host=None, publisher=None):
    """Publish every scheduled one-image Reel whose time has come.

    Network failures are retried a few times (see SCHEDULE_RETRY_MINUTES);
    any other failure is recorded and not retried until the Reel is
    rescheduled, so a broken token cannot cause repeated attempts.
    """
    now = now or datetime.now(timezone.utc)
    results = []
    for path in sorted(_CONTENT_DIRECTORIES["post"].glob("post_*.json")):
        content_id = path.stem
        try:
            record = load_post(content_id)
        except (PostStorageError, FileNotFoundError):
            continue
        scheduled = record.get("scheduled_at")
        if (
            not scheduled
            or not _is_image_reel(record)
            or record.get("status") != "Approved"
            or record.get("schedule_failed")
            or _parse_schedule(scheduled) > now
            or (
                record.get("schedule_retry_at")
                and _parse_schedule(record["schedule_retry_at"]) > now
            )
        ):
            continue
        attempts = int(record.get("schedule_attempts") or 0)
        try:
            if attempts:
                publisher = publisher or InstagramPublisher()
                copy = _published_copy(
                    record, publisher, _parse_schedule(scheduled) - timedelta(minutes=5)
                )
                if copy:
                    record = load_post(content_id)
                    record.update(
                        status="Published",
                        instagram_media_id=copy["id"],
                        instagram_permalink=copy.get("permalink"),
                        published_at=copy["timestamp"],
                    )
                    for key in ("scheduled_at", "schedule_attempts",
                                "schedule_retry_at", "schedule_last_error"):
                        record.pop(key, None)
                    save_post(content_id, record)
                    _append_history("post", content_id, "found_already_published",
                                    permalink=copy.get("permalink"))
                    results.append((content_id, "published", copy.get("permalink")))
                    continue
            result = publish_content(
                "post", content_id, host=host, publisher=publisher
            )
            results.append((content_id, "published", result.get("permalink")))
        except (*_STAGE_ACTION_ERRORS, ValueError) as error:
            record = load_post(content_id)
            if _is_transient(error) and attempts < len(SCHEDULE_RETRY_MINUTES):
                wait = SCHEDULE_RETRY_MINUTES[attempts]
                record.update(
                    schedule_attempts=attempts + 1,
                    schedule_retry_at=(now + timedelta(minutes=wait)).isoformat(),
                    schedule_last_error=str(error),
                )
                save_post(content_id, record)
                results.append(
                    (content_id, "retrying", f"{error} Trying again in {wait} minutes.")
                )
                continue
            record["schedule_failed"] = str(error)
            for key in ("schedule_attempts", "schedule_retry_at"):
                record.pop(key, None)
            save_post(content_id, record)
            results.append((content_id, "failed", str(error)))
    return results


def mark_posted(content_type, content_id, permalink=None):
    """Record that a one-image Reel was posted by hand in the Instagram app."""
    if content_type != "post":
        raise ValueError("Only posts can be marked as posted.")
    record = load_post(content_id)
    if not _is_image_reel(record):
        raise ValueError("Only one-image Reels are posted by hand.")
    if record.get("status") != "Approved":
        raise ValueError("Only Approved, unposted content can be marked as posted.")
    if not reel_video_path(content_id).is_file():
        raise ValueError("Render the Reel video before marking it as posted.")
    if permalink is not None and not isinstance(permalink, str):
        raise ValueError("The Instagram link must be text.")
    permalink = (permalink or "").strip() or None
    if permalink and not re.fullmatch(
        r"https://(www\.)?instagram\.com/\S+", permalink
    ):
        raise ValueError("The link must be an instagram.com URL.")
    record.update(
        status="Published",
        published_manually=True,
        published_at=datetime.now(timezone.utc).isoformat(),
    )
    if permalink:
        record["instagram_permalink"] = permalink
    save_post(content_id, record)
    _append_history(
        content_type, content_id, "stage_ready",
        stage="publishing", source="manual", permalink=permalink,
    )
    return record


def publish_content(
    content_type, content_id, dry_run=False, host=None, publisher=None
):
    """Upload an approved, rendered post and publish it to Instagram.

    Feed posts publish their image; one-image Reels publish their MP4 as a
    Reel. The media is uploaded only now, after human review; with dry_run
    the upload happens but nothing is posted to Instagram.
    """
    if content_type != "post":
        raise ValueError("Only posts can be published to Instagram.")
    record = load_post(content_id)
    is_reel = _is_image_reel(record)
    if not (is_reel or _is_instagram_post(record)):
        raise ValueError("Only Instagram posts and Reels can be published.")
    if record.get("status") != "Approved" or record.get("instagram_media_id"):
        raise ValueError("Only Approved, unpublished posts can be published.")
    image_path = reel_video_path(content_id) if is_reel else post_image_path(content_id)
    if not image_path.is_file():
        raise ValueError(
            "Render and review the Reel video before publishing."
            if is_reel
            else "Render and review the Instagram image before publishing."
        )
    caption = validate_instagram_caption(strip_highlights(record.get("caption") or ""))
    stage_key = (content_type, content_id, "publishing")
    with _STAGE_LOCK:
        if stage_key in _ACTIVE_STAGES:
            raise ValueError("This post is already being published.")
        _ACTIVE_STAGES.add(stage_key)
    uploaded_keys = []
    try:
        _append_history(
            content_type, content_id, "stage_started",
            stage="publishing", dry_run=dry_run,
        )
        host = host or R2MediaHost()
        key, media_url = host.upload(image_path, content_id)
        uploaded_keys.append(key)
        cover_url = None
        cover_path = post_image_path(content_id)
        if is_reel and cover_path.is_file():
            # The rendered still (with the text) becomes the grid cover.
            cover_key, cover_url = host.upload(cover_path, content_id)
            uploaded_keys.append(cover_key)
        if dry_run:
            _append_history(
                content_type, content_id, "publish_dry_run",
                stage="publishing", media_url=media_url,
            )
            return {"dry_run": True, "media_url": media_url}
        publisher = publisher or InstagramPublisher()
        if is_reel:
            result = publisher.publish_reel(
                media_url,
                caption,
                thumb_offset_ms=REEL_COVER_OFFSET_MS,
                cover_url=cover_url,
            )
        else:
            result = publisher.publish_image(media_url, caption)
        record = load_post(content_id)
        record.update(
            status="Published",
            instagram_media_id=result["media_id"],
            instagram_permalink=result["permalink"],
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        if result.get("ai_label") is not None:
            record["instagram_ai_label"] = bool(result["ai_label"])
        record.pop("scheduled_at", None)
        save_post(content_id, record)
        _append_history(
            content_type, content_id, "stage_ready",
            stage="publishing", permalink=result["permalink"],
        )
        for uploaded_key in uploaded_keys:
            try:
                host.delete(uploaded_key)  # Instagram keeps its own copy.
            except MediaHostError:
                pass
        return {"dry_run": False, **result}
    except _STAGE_ACTION_ERRORS as error:
        _append_history(
            content_type, content_id, "stage_failed",
            stage="publishing", error=str(error),
        )
        # Do not leave public copies behind when the publish did not finish.
        for uploaded_key in uploaded_keys:
            try:
                host.delete(uploaded_key)
            except MediaHostError:
                pass
        raise
    finally:
        with _STAGE_LOCK:
            _ACTIVE_STAGES.discard(stage_key)


def regenerate_content(content_type, content_id):
    record = get_content_item(content_type, content_id)
    if record.get("status", "Draft") not in ("Draft", "Rejected"):
        raise ValueError("Only Draft or Rejected content can be regenerated.")
    result = generate_and_save(
        {
            "brand_id": (
                ""
                if "brand_id" in record and record["brand_id"] is None
                else record.get("brand_id")
            ),
            "profile_id": record.get("profile_id"),
            "format_id": record.get("format_id"),
            "platform_id": record.get("platform_id"),
            "brief": record.get("brief"),
            "category_id": record.get("category_id"),
            "comedy_subtype": record.get("comedy_subtype"),
            "subtype": record.get("subtype") or record.get("qa_subtype"),
            "thinker_id": record.get("thinker_id"),
            "visual_style": record.get("visual_style"),
            "caption_language": record.get("caption_language"),
        }
    )
    _append_history(
        content_type,
        content_id,
        "regenerated_as",
        new_content_id=result["id"],
    )
    _append_history(
        result["type"],
        result["id"],
        "content_generated",
        title=result["title"],
        regenerated_from=content_id,
    )
    return result


def get_generation_options():
    loaders = {
        "brands": load_brand,
        "profiles": load_profile_config,
        "formats": load_format,
        "platforms": load_platform,
    }
    directories = {
        "brands": CONFIG_DIRECTORY / "brands",
        "profiles": CONFIG_DIRECTORY / "content_profiles",
        "formats": CONFIG_DIRECTORY / "formats",
        "platforms": CONFIG_DIRECTORY / "platforms",
    }
    options = {}
    for kind, directory in directories.items():
        options[kind] = []
        for path in sorted(directory.glob("*.yaml")):
            model = loaders[kind](path.stem)
            option = {"id": model.id, "name": model.display_name}
            if kind == "formats":
                option.update(
                    {
                        "content_kind": model.content_kind,
                        "aspect_ratio": model.aspect_ratio,
                        "content_fields": list(model.content_fields),
                    }
                )
            elif kind == "platforms":
                option["supported_format_ids"] = list(
                    model.supported_format_ids
                )
            elif kind == "brands":
                option.update(
                    {
                        "default_profile_id": model.default_profile_id,
                        "default_format_id": model.default_format_id,
                        "default_platform_id": model.default_platform_id,
                    }
                )
            options[kind].append(option)
    try:
        comedy = load_comedy_config()
    except ConfigurationError as error:
        options["categories"] = []
        options["comedy_subtypes"] = []
        options["category_error"] = str(error)
    else:
        options["categories"] = (
            [{"id": comedy["id"], "name": comedy["display_name"]}]
            if comedy.get("enabled", True)
            else []
        )
        options["comedy_subtypes"] = (
            [
                {"id": item["id"], "name": item["name"]}
                for item in comedy["subtypes"]
            ]
            if comedy.get("enabled", True)
            else []
        )
        options["category_error"] = (
            "Comedy category is currently disabled."
            if not comedy.get("enabled", True)
            else ""
        )
    try:
        options["qa_subtypes"] = [
            {"id": item["id"], "name": item["name"]}
            for item in load_profile_subtypes("qa_engineering_ai")
        ]
        options["qa_subtype_error"] = ""
    except ConfigurationError as error:
        options["qa_subtypes"] = []
        options["qa_subtype_error"] = str(error)
    options["profile_subtypes"] = {
        "comedy": options["comedy_subtypes"],
        "qa_engineering_ai": options["qa_subtypes"],
    }
    options["music_tracks"] = [path.name for path in list_tracks()]
    options["profile_thinkers"] = {}
    options["profile_visual_styles"] = {}
    profile_errors = []
    for profile in options.get("profiles", []):
        try:
            styles = load_profile_visual_styles(profile["id"])
        except ConfigurationError as error:
            profile_errors.append(str(error))
            continue
        if styles:
            options["profile_visual_styles"][profile["id"]] = [
                {"id": item["id"], "name": item["name"]} for item in styles
            ]
    for profile in options.get("profiles", []):
        profile_id = profile["id"]
        if profile_id in options["profile_subtypes"]:
            continue
        try:
            subtypes = load_profile_subtypes(profile_id)
            thinkers = load_profile_thinkers(profile_id)
        except ConfigurationError as error:
            profile_errors.append(str(error))
            continue
        if subtypes:
            options["profile_subtypes"][profile_id] = [
                {"id": item["id"], "name": item["name"]} for item in subtypes
            ]
        if thinkers:
            options["profile_thinkers"][profile_id] = [
                {"id": item["id"], "name": item["name"]} for item in thinkers
            ]
    options["subtype_error"] = "; ".join(
        error
        for error in (
            options.get("category_error", ""),
            options.get("qa_subtype_error", ""),
            *profile_errors,
        )
        if error
    )
    return options


def generate_and_save(payload):
    if not isinstance(payload, dict):
        raise ValueError("Generation request must be a JSON object.")
    brief = payload.get("brief")
    if brief is not None and not isinstance(brief, str):
        raise ValueError("Brief must be text.")
    if brief is not None and not brief.strip():
        raise ValueError("Brief must not be empty.")

    profile_id = payload.get("profile_id")
    category_id = payload.get("category_id")
    comedy_subtype = payload.get("comedy_subtype")
    # "qa_subtype" is the legacy name for "subtype".
    subtype = payload.get("subtype") or payload.get("qa_subtype")
    content_subtype = payload.get("content_subtype")
    if content_subtype:
        if profile_id == "comedy":
            category_id = "comedy"
            comedy_subtype = content_subtype
        elif profile_id:
            subtype = content_subtype
        else:
            raise ValueError("Content subtypes require a content profile.")

    result = generate_content(
        brand_id=payload.get("brand_id"),
        profile_id=payload.get("profile_id"),
        format_id=payload.get("format_id"),
        platform_id=payload.get("platform_id"),
        brief=brief.strip() if brief else None,
        category_id=category_id,
        comedy_subtype=comedy_subtype,
        subtype=subtype,
        thinker_id=payload.get("thinker_id") or None,
        visual_style=payload.get("visual_style") or None,
        caption_language=payload.get("caption_language") or "english",
    )
    data = {
        "brand_id": (
            result.request.brand.id if result.request.brand is not None else None
        ),
        "profile_id": result.request.profile.id,
        "format_id": result.request.content_format.id,
        "platform_id": result.request.platform.id,
        "brief": result.request.brief,
        **result.content.to_legacy_mapping(),
        "status": "Draft",
    }
    if result.request.category_id:
        data["category_id"] = result.request.category_id
        if result.request.comedy_subtype:
            data["comedy_subtype"] = result.request.comedy_subtype
    if result.request.subtype:
        data["subtype"] = result.request.subtype
    if result.request.thinker_id:
        data["thinker_id"] = result.request.thinker_id
    if result.request.visual_style:
        data["visual_style"] = result.request.visual_style
    if payload.get("caption_language") == "hinglish":
        data["caption_language"] = "hinglish"
    if result.request.content_format.id == "image_reel":
        data["layout"] = "poster"

    if result.request.content_format.content_kind == "post":
        content_id, file_path = create_post(data)
        prompt_path = None
        if "design_prompt" in result.content.fields:
            brand = result.request.brand
            prompt = build_post_prompt_file(
                data,
                result.request.content_format,
                result.request.platform,
                result.request.category_id,
                brand.template.art_style if brand else None,
            )
            prompt_path = GENERATED_ASSETS_DIRECTORY / (
                f"{content_id}_design_prompt.txt"
            )
            try:
                GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text(prompt + "\n", encoding="utf-8")
            except OSError as error:
                raise ReviewUIError(
                    f"Post {content_id} was saved, but its design prompt "
                    f"could not be written to {prompt_path}: {error}"
                ) from error
        content_type = "post"
    else:
        content_id, file_path = create_reel(data)
        prompt_path = None
        content_type = "reel"

    return {
        "id": content_id,
        "type": content_type,
        "title": result.content.fields.get("title", "Untitled"),
        "status": "Draft",
        "path": str(file_path),
        "design_prompt_path": str(prompt_path) if prompt_path else None,
    }


def generate_batch_and_save(payload):
    count = payload.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10:
        raise ValueError("Draft count must be an integer between 1 and 10.")
    subtype_ids = ()
    if (
        count > 1
        and (
            payload.get("profile_id") == "comedy"
            or payload.get("category_id") == "comedy"
        )
        and not (
            payload.get("content_subtype")
            or payload.get("comedy_subtype")
        )
    ):
        subtype_ids = tuple(
            subtype["id"] for subtype in load_comedy_config()["subtypes"]
        )
    qa_subtype_ids = ()
    thinker_ids = ()
    profile_id = payload.get("profile_id")
    if count > 1 and profile_id and profile_id != "comedy":
        if not (
            payload.get("content_subtype")
            or payload.get("subtype")
            or payload.get("qa_subtype")
        ):
            qa_subtype_ids = tuple(
                subtype["id"] for subtype in load_profile_subtypes(profile_id)
            )
        if not payload.get("thinker_id"):
            thinker_ids = tuple(
                thinker["id"] for thinker in load_focus_thinkers(profile_id)
            )

    items = []
    for index in range(count):
        request = dict(payload)
        if subtype_ids:
            if request.get("profile_id") == "comedy":
                request["content_subtype"] = subtype_ids[
                    index % len(subtype_ids)
                ]
            else:
                request["comedy_subtype"] = subtype_ids[
                    index % len(subtype_ids)
                ]
        if qa_subtype_ids:
            request["content_subtype"] = qa_subtype_ids[
                index % len(qa_subtype_ids)
            ]
        if thinker_ids:
            request["thinker_id"] = thinker_ids[index % len(thinker_ids)]
        try:
            items.append(generate_and_save(request))
        except (
            AIServiceError,
            ConfigurationError,
            ContentValidationError,
            PostStorageError,
            ReelStorageError,
            ReviewUIError,
            ValueError,
        ) as error:
            if items:
                raise PartialGenerationError(
                    f"Batch stopped after saving {len(items)} of {count} "
                    f"drafts: {error}. The saved drafts remain in the library."
                ) from error
            raise
    return items


def main(argv=None):
    """Start the review UI server (the HTTP layer is in review_server)."""
    from scripts.review_server import main as serve

    return serve(argv)


def __getattr__(name):
    # Keep review_ui.ReviewRequestHandler available without a circular import.
    if name == "ReviewRequestHandler":
        from scripts.review_server import ReviewRequestHandler

        return ReviewRequestHandler
    raise AttributeError(name)


if __name__ == "__main__":
    raise SystemExit(main())
