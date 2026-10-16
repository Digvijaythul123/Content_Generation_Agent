import argparse
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

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
from post_storage import PostStorageError, create_post
from project_paths import (
    CONFIG_DIRECTORY,
    GENERATED_ASSETS_DIRECTORY,
    GENERATED_POSTS_DIRECTORY,
    GENERATED_REELS_DIRECTORY,
)
from reel_storage import ReelStorageError, create_reel


UI_FILE = Path(__file__).with_name("review_ui.html")
_CONTENT_DIRECTORIES = {
    "reel": GENERATED_REELS_DIRECTORY,
    "post": GENERATED_POSTS_DIRECTORY,
}
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_REQUEST_BYTES = 64 * 1024


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
                    "profile_id": record.get("profile_id", ""),
                    "format_id": record.get(
                        "format_id", "reel" if content_type == "reel" else ""
                    ),
                    "platform_id": record.get("platform_id", ""),
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
        if request.path != "/api/generate":
            self.send_error(404, "Not found")
            return
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
            result = generate_and_save(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._send_json({"error": f"Invalid JSON request: {error}"}, 400)
            return
        except (ConfigurationError, ContentValidationError, ValueError) as error:
            self._send_json({"error": str(error)}, 400)
            return
        except AIServiceError as error:
            self._send_json({"error": str(error)}, 502)
            return
        except (PostStorageError, ReelStorageError, ReviewUIError) as error:
            self._send_json({"error": str(error)}, 500)
            return
        self._send_json({"item": result}, status=201)

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

    def _send_bytes(self, body, content_type, status):
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
