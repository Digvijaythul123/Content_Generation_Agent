import argparse
from datetime import datetime, timezone
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, quote, urlsplit

from ai_service import AIServiceError
from config_loader import (
    ConfigurationError,
    load_brand,
    load_format,
    load_platform,
    load_profile_config,
)
from content_models import ContentValidationError
from content_pipeline import generate_content
from post_prompt import build_ready_design_prompt
from post_storage import (
    PostStorageError,
    create_post,
    load_post,
    save_post,
)
from project_paths import (
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
    OSError,
    ValueError,
)


class ReviewUIError(RuntimeError):
    """Raised when saved content cannot be read by the review UI."""


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
                    "brand_id": record.get("brand_id", ""),
                    "profile_id": record.get("profile_id", ""),
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


def _asset_paths(content_type, content_id):
    if content_type == "post":
        return [
            (
                "design_prompt",
                "Design prompt",
                "Image prompt",
                GENERATED_ASSETS_DIRECTORY
                / f"{content_id}_design_prompt.txt",
            )
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
        if record is not None and "design_prompt" not in record:
            return {}
        return {"design_prompt": GENERATED_ASSETS_DIRECTORY
                / f"{content_id}_design_prompt.txt"}
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
                if record.get("status") in ("Approved", "Rejected")
                else "not_started"
            ),
            "available": True,
        },
        {
            "id": "approval",
            "label": "Approved",
            "status": (
                "ready"
                if record.get("status") == "Approved"
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
        ([("design_prompt", "Design prompt")] if "design_prompt" in record else [])
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
                    "Generate a storyboard first."
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
        [
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
            {
                "id": "publishing",
                "label": "Published",
                "status": "future",
                "available": False,
                "reason": "Publishing is not integrated yet.",
            },
        ]
    )
    return {"stages": common}


def get_dashboard_summary():
    items = list_content_items()
    counts = {
        "total": len(items),
        "drafts": sum(item["status"] == "Draft" for item in items),
        "approved": sum(item["status"] == "Approved" for item in items),
        "rejected": sum(item["status"] == "Rejected" for item in items),
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
        else:
            format_id = record.get("format_id", "single_page")
            platform_id = record.get("platform_id", "instagram_feed")
            if stage != "design_prompt":
                raise ValueError(
                    f"Stage is not supported for {content_type}: {stage}"
                )
            prompt = build_ready_design_prompt(
                record, load_format(format_id), load_platform(platform_id)
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


def regenerate_content(content_type, content_id):
    record = get_content_item(content_type, content_id)
    if record.get("status", "Draft") not in ("Draft", "Rejected"):
        raise ValueError("Only Draft or Rejected content can be regenerated.")
    result = generate_and_save(
        {
            "brand_id": record.get("brand_id"),
            "profile_id": record.get("profile_id"),
            "format_id": record.get("format_id"),
            "platform_id": record.get("platform_id"),
            "brief": record.get("brief"),
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
    return options


def generate_and_save(payload):
    if not isinstance(payload, dict):
        raise ValueError("Generation request must be a JSON object.")
    brief = payload.get("brief")
    if brief is not None and not isinstance(brief, str):
        raise ValueError("Brief must be text.")
    if brief is not None and not brief.strip():
        raise ValueError("Brief must not be empty.")

    result = generate_content(
        brand_id=payload.get("brand_id"),
        profile_id=payload.get("profile_id"),
        format_id=payload.get("format_id"),
        platform_id=payload.get("platform_id"),
        brief=brief.strip() if brief else None,
    )
    data = {
        "brand_id": result.request.brand.id,
        "profile_id": result.request.profile.id,
        "format_id": result.request.content_format.id,
        "platform_id": result.request.platform.id,
        "brief": result.request.brief,
        **result.content.to_legacy_mapping(),
        "status": "Draft",
    }

    if result.request.content_format.content_kind == "post":
        content_id, file_path = create_post(data)
        prompt_path = None
        if "design_prompt" in result.content.fields:
            prompt = build_ready_design_prompt(
                result.content.fields,
                result.request.content_format,
                result.request.platform,
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


class ReviewRequestHandler(BaseHTTPRequestHandler):
    server_version = "LocalContentReview/1.0"

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path in ("/", "/index.html"):
            self._send_file(UI_FILE, "text/html; charset=utf-8")
            return
        if request.path == "/api/options":
            try:
                self._send_json(get_generation_options())
            except ConfigurationError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if request.path == "/api/dashboard":
            try:
                self._send_json(get_dashboard_summary())
            except ReviewUIError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if request.path == "/api/activity":
            try:
                self._send_json({"items": get_recent_activity()})
            except ReviewUIError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        path_parts = request.path.strip("/").split("/")
        if (
            len(path_parts) == 5
            and path_parts[0:2] == ["api", "content"]
            and path_parts[4] in ("pipeline", "assets", "history")
        ):
            content_type, content_id, resource = (
                path_parts[2],
                path_parts[3],
                path_parts[4],
            )
            try:
                if resource == "pipeline":
                    self._send_json(get_pipeline(content_type, content_id))
                elif resource == "assets":
                    self._send_json({"items": list_assets(content_type, content_id)})
                else:
                    self._send_json(
                        {"items": get_history(content_type, content_id)}
                    )
            except KeyError as error:
                self._send_json({"error": str(error)}, status=404)
            except (ReviewUIError, PostStorageError, ReelStorageError) as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if len(path_parts) == 5 and path_parts[:2] == ["api", "assets"]:
            try:
                name, asset_type, body = read_asset(
                    path_parts[2], path_parts[3], path_parts[4]
                )
            except KeyError as error:
                self._send_json({"error": str(error)}, status=404)
                return
            except (ReviewUIError, PostStorageError, ReelStorageError) as error:
                self._send_json({"error": str(error)}, status=500)
                return
            mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if mime_type.startswith("text/") or mime_type == "application/json":
                self._send_json(
                    {
                        "name": name,
                        "type": asset_type,
                        "content": body.decode("utf-8"),
                    }
                )
                return
            self._send_bytes(
                body,
                mime_type,
                200,
                extra_headers={
                    "Content-Disposition": (
                        f"inline; filename*=UTF-8''{quote(name, safe='')}"
                    ),
                    "X-Asset-Type": asset_type,
                },
            )
            return
        if request.path != "/api/content":
            self.send_error(404, "Not found")
            return

        query = parse_qs(request.query)
        try:
            if "id" in query or "type" in query:
                if len(query.get("id", [])) != 1 or len(
                    query.get("type", [])
                ) != 1:
                    raise KeyError(
                        "Both one content type and one content ID are required."
                    )
                content_type = query["type"][0]
                record = get_content_item(content_type, query["id"][0])
                self._send_json({"type": content_type, "record": record})
            else:
                self._send_json({"items": list_content_items()})
        except KeyError as error:
            self._send_json({"error": str(error)}, status=404)
        except ReviewUIError as error:
            self._send_json({"error": str(error)}, status=500)

    def do_POST(self):
        request = urlsplit(self.path)
        if not self._is_same_origin_loopback_request():
            self._send_json({"error": "Local same-origin request required."}, 403)
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json({"error": "Content-Type must be application/json."}, 415)
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, 400)
            return
        if not 0 < content_length <= _MAX_REQUEST_BYTES:
            self._send_json({"error": "Request body size is invalid."}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._send_json({"error": f"Invalid JSON request: {error}"}, 400)
            return
        if not isinstance(payload, dict):
            self._send_json({"error": "Request body must be a JSON object."}, 400)
            return
        if request.path == "/api/generate":
            try:
                result = generate_and_save(payload)
                _append_history(
                    result["type"],
                    result["id"],
                    "content_generated",
                    title=result["title"],
                )
            except AIServiceError as error:
                self._send_json({"error": str(error)}, 502)
                return
            except (
                PostStorageError,
                ReelStorageError,
                ReviewUIError,
            ) as error:
                self._send_json({"error": str(error)}, 500)
                return
            except (
                ConfigurationError,
                ContentValidationError,
                ValueError,
            ) as error:
                self._send_json({"error": str(error)}, 400)
                return
            self._send_json({"item": result}, status=201)
            return
        path_parts = request.path.strip("/").split("/")
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "review"
        ):
            try:
                record = review_content(
                    path_parts[2],
                    path_parts[3],
                    payload.get("decision"),
                    payload.get("reason", ""),
                )
                self._send_json({"record": record})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (PostStorageError, ReelStorageError, ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "regenerate"
        ):
            try:
                result = regenerate_content(path_parts[2], path_parts[3])
                self._send_json({"item": result}, status=201)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, status=404)
            except AIServiceError as error:
                self._send_json({"error": str(error)}, status=502)
            except (
                PostStorageError,
                ReelStorageError,
                ReviewUIError,
            ) as error:
                self._send_json({"error": str(error)}, status=500)
            except (
                ConfigurationError,
                ContentValidationError,
                ValueError,
            ) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if (
            len(path_parts) == 7
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "stages"
            and path_parts[6] == "run"
        ):
            try:
                result = run_production_stage(
                    path_parts[2], path_parts[3], path_parts[5]
                )
                self._send_json(result)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except AIServiceError as error:
                self._send_json({"error": str(error)}, 502)
            except (PostStorageError, ReelStorageError, OSError, ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except (ConfigurationError, StoryboardValidationError, ValueError) as error:
                self._send_json({"error": str(error)}, 400)
            return
        self.send_error(404, "Not found")


    def _is_same_origin_loopback_request(self):
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if not origin or not host:
            return False
        parsed_origin = urlsplit(origin)
        return (
            parsed_origin.scheme == "http"
            and parsed_origin.netloc == host
            and parsed_origin.hostname in ("127.0.0.1", "localhost", "::1")
        )

    def _send_file(self, path, content_type):
        try:
            body = path.read_bytes()
        except OSError as error:
            self._send_json({"error": f"Could not read UI file: {error}"}, 500)
            return
        self._send_bytes(body, content_type, status=200)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(self, body, content_type, status, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'",
        )
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the local content review and generation UI."
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Local server port (default: 8765)."
    )
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port must be between 1 and 65535.")

    try:
        with ThreadingHTTPServer(
            ("127.0.0.1", args.port), ReviewRequestHandler
        ) as server:
            print(
                "Content workspace available at "
                f"http://127.0.0.1:{args.port} (Ctrl+C to stop)"
            )
            server.serve_forever()
    except OSError as error:
        print(f"Could not start content workspace: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nContent workspace stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
