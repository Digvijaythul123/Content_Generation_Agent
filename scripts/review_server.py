"""HTTP layer for the local review UI (requests, responses, and server start).

The content, production, and publishing logic lives in scripts/review_ui.py;
this module calls it through ``ui.`` so tests that patch review_ui still apply.
"""

import argparse
import ipaddress
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from scripts import review_ui as ui


class ReviewRequestHandler(BaseHTTPRequestHandler):
    server_version = "LocalContentReview/1.0"

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path in ("/", "/index.html"):
            self._send_file(ui.UI_FILE, "text/html; charset=utf-8")
            return
        if request.path == "/api/options":
            try:
                self._send_json(ui.get_generation_options())
            except ui.ConfigurationError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if request.path == "/api/performance":
            self._send_json({"report": ui.cached_report()})
            return
        if request.path == "/api/best_times":
            self._send_json(ui.best_posting_hours())
            return
        if request.path == "/api/calendar":
            self._send_json({"items": ui.upcoming_observances()})
            return
        if request.path == "/api/dashboard":
            try:
                self._send_json(ui.get_dashboard_summary())
            except ui.ReviewUIError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if request.path == "/api/artwork_sources":
            self._send_json({"items": ui.list_importable_images()})
            return
        if request.path.startswith("/api/artwork_sources/"):
            try:
                path = ui._importable_image_path(
                    unquote(request.path[len("/api/artwork_sources/"):])
                )
                body = path.read_bytes()
            except KeyError as error:
                self._send_json({"error": str(error)}, 404)
                return
            except OSError as error:
                self._send_json({"error": str(error)}, 500)
                return
            self._send_bytes(
                body, mimetypes.guess_type(path.name)[0] or "image/png", 200
            )
            return
        if request.path == "/api/activity":
            try:
                self._send_json({"items": ui.get_recent_activity()})
            except ui.ReviewUIError as error:
                self._send_json({"error": str(error)}, status=500)
            return
        path_parts = request.path.strip("/").split("/")
        if (
            len(path_parts) == 5
            and path_parts[0:2] == ["api", "content"]
            and path_parts[4] in ("pipeline", "assets", "history", "art_prompt", "flow_prompt")
        ):
            content_type, content_id, resource = (
                path_parts[2],
                path_parts[3],
                path_parts[4],
            )
            try:
                if resource == "pipeline":
                    self._send_json(ui.get_pipeline(content_type, content_id))
                elif resource == "art_prompt":
                    self._send_json(
                        {"prompt": ui.get_art_prompt(content_type, content_id)}
                    )
                elif resource == "flow_prompt":
                    self._send_json(
                        {"prompt": ui.get_flow_prompt(content_type, content_id)}
                    )
                elif resource == "assets":
                    self._send_json({"items": ui.list_assets(content_type, content_id)})
                else:
                    self._send_json(
                        {"items": ui.get_history(content_type, content_id)}
                    )
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, status=404)
            except (ui.ReviewUIError, ui.PostStorageError, ui.ReelStorageError) as error:
                self._send_json({"error": str(error)}, status=500)
            except (ui.ArtGenerationError, ValueError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if len(path_parts) == 5 and path_parts[:2] == ["api", "assets"]:
            try:
                name, asset_type, body = ui.read_asset(
                    path_parts[2], path_parts[3], path_parts[4]
                )
            except KeyError as error:
                self._send_json({"error": str(error)}, status=404)
                return
            except (ui.ReviewUIError, ui.PostStorageError, ui.ReelStorageError) as error:
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
                record = ui.get_content_item(content_type, query["id"][0])
                self._send_json({"type": content_type, "record": record})
            else:
                self._send_json({"items": ui.list_content_items()})
        except KeyError as error:
            self._send_json({"error": str(error)}, status=404)
        except ui.ReviewUIError as error:
            self._send_json({"error": str(error)}, status=500)

    def do_POST(self):
        request = urlsplit(self.path)
        if not self._is_same_origin_loopback_request():
            self._send_json({"error": "Local same-origin request required."}, 403)
            return
        path_parts = request.path.strip("/").split("/")
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "artwork"
        ):
            self._handle_artwork_upload(path_parts[2], path_parts[3])
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json({"error": "Content-Type must be application/json."}, 415)
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, 400)
            return
        if not 0 < content_length <= ui._MAX_REQUEST_BYTES:
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
        if request.path == "/api/plan_week":
            try:
                self._send_json({"planned": ui.plan_week()})
            except ui.AIServiceError as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.ConfigurationError, ValueError) as error:
                self._send_json({"error": str(error)}, 400)
            return
        if request.path == "/api/performance/refresh":
            try:
                self._send_json({"report": ui.refresh_report()})
            except (ui.InstagramPublishError, OSError) as error:
                self._send_json({"error": str(error)}, 502)
            return
        if request.path == "/api/generate":
            try:
                results = ui.generate_batch_and_save(payload)
                for result in results:
                    ui._append_history(
                        result["type"],
                        result["id"],
                        "content_generated",
                        title=result["title"],
                    )
            except ui.AIServiceError as error:
                self._send_json({"error": str(error)}, 502)
                return
            except (
                ui.PostStorageError,
                ui.ReelStorageError,
                ui.ReviewUIError,
            ) as error:
                self._send_json({"error": str(error)}, 500)
                return
            except (
                ui.ConfigurationError,
                ui.ContentValidationError,
                ValueError,
            ) as error:
                self._send_json({"error": str(error)}, 400)
                return
            if len(results) == 1:
                self._send_json({"item": results[0]}, status=201)
            else:
                self._send_json({"items": results}, status=201)
            return
        path_parts = request.path.strip("/").split("/")
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "first_comment"
        ):
            try:
                self._send_json({"comment_id": ui.post_first_comment(path_parts[3])})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except ui.InstagramPublishError as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.PostStorageError, ui.ReviewUIError, OSError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "threads"
        ):
            try:
                self._send_json({"result": ui.post_to_threads(path_parts[3])})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.ThreadsPublishError, ui.MediaHostError) as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.PostStorageError, ui.ReviewUIError, OSError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "facebook"
        ):
            try:
                self._send_json({"result": ui.post_to_facebook(path_parts[3])})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except ui.FacebookPublishError as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.PostStorageError, ui.ReviewUIError, OSError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "simplify"
        ):
            try:
                fresh = bool(payload.get("fresh"))
                self._send_json(
                    {"suggestion": ui.simplify_post_text(path_parts[3], fresh=fresh)}
                )
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except ui.AIServiceError as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.PostStorageError, ui.ReviewUIError, OSError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "convert_to_reel"
        ):
            try:
                record = ui.convert_to_reel(path_parts[3])
                self._send_json({"record": record})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.PostStorageError, ui.ReviewUIError, OSError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:3] == ["api", "content", "post"]
            and path_parts[4] == "settings"
        ):
            try:
                record = ui.update_post_settings(path_parts[3], payload)
                self._send_json({"record": record})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.PostStorageError, ui.ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except (ui.ContentValidationError, ValueError) as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "mark_posted"
        ):
            try:
                record = ui.mark_posted(
                    path_parts[2], path_parts[3], payload.get("permalink")
                )
                self._send_json({"record": record})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.PostStorageError, ui.ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "review"
        ):
            try:
                record = ui.review_content(
                    path_parts[2],
                    path_parts[3],
                    payload.get("decision"),
                    payload.get("reason", ""),
                )
                self._send_json({"record": record})
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.PostStorageError, ui.ReelStorageError, ui.ReviewUIError) as error:
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
                result = ui.regenerate_content(path_parts[2], path_parts[3])
                self._send_json({"item": result}, status=201)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, status=404)
            except ui.AIServiceError as error:
                self._send_json({"error": str(error)}, status=502)
            except (
                ui.PostStorageError,
                ui.ReelStorageError,
                ui.ReviewUIError,
            ) as error:
                self._send_json({"error": str(error)}, status=500)
            except (
                ui.ConfigurationError,
                ui.ContentValidationError,
                ValueError,
            ) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "artwork_import"
        ):
            try:
                result = ui.import_artwork(
                    path_parts[2], path_parts[3], payload.get("image_id")
                )
                self._send_json(result)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.PostStorageError, OSError, ui.ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except (ui.ArtGenerationError, ui.ConfigurationError, ValueError) as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 5
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "publish"
        ):
            if payload.get("confirm") is not True:
                self._send_json(
                    {"error": "Publishing requires explicit confirmation."}, 400
                )
                return
            try:
                result = ui.publish_content(path_parts[2], path_parts[3])
                self._send_json(result)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.InstagramPublishError, ui.MediaHostError) as error:
                self._send_json({"error": str(error)}, 502)
            except (ui.PostStorageError, OSError, ui.ReviewUIError) as error:
                self._send_json({"error": str(error)}, 500)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if (
            len(path_parts) == 7
            and path_parts[:2] == ["api", "content"]
            and path_parts[4] == "stages"
            and path_parts[6] == "run"
        ):
            try:
                result = ui.run_production_stage(
                    path_parts[2], path_parts[3], path_parts[5]
                )
                self._send_json(result)
            except (KeyError, FileNotFoundError) as error:
                self._send_json({"error": str(error)}, 404)
            except (ui.AIServiceError, ui.ArtGenerationError) as error:
                self._send_json({"error": str(error)}, 502)
            except (
                ui.PostStorageError, ui.ReelStorageError, OSError, ui.ReviewUIError,
                ui.MediaRenderError,
            ) as error:
                self._send_json({"error": str(error)}, 500)
            except (ui.ConfigurationError, ui.StoryboardValidationError, ValueError) as error:
                self._send_json({"error": str(error)}, 400)
            return
        self.send_error(404, "Not found")


    def _handle_artwork_upload(self, content_type, content_id):
        media_type = self.headers.get_content_type()
        if media_type not in (
            "image/png", "image/jpeg", "image/webp", "video/mp4", "video/quicktime"
        ):
            self._send_json(
                {"error": "Upload a PNG, JPEG, or WebP image, or an MP4/MOV clip."}, 415
            )
            return
        limit = (
            ui.MAX_VIDEO_ARTWORK_BYTES if media_type.startswith("video/") else ui.MAX_ARTWORK_BYTES
        )
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, 400)
            return
        if not 0 < content_length <= limit:
            self._send_json(
                {"error": f"Artwork must be {limit // (1024 * 1024)} MB or smaller."}, 413
            )
            return
        try:
            result = ui.upload_artwork(
                content_type, content_id, self.rfile.read(content_length)
            )
            self._send_json(result)
        except (KeyError, FileNotFoundError) as error:
            self._send_json({"error": str(error)}, 404)
        except (ui.PostStorageError, OSError, ui.ReviewUIError) as error:
            self._send_json({"error": str(error)}, 500)
        except (ui.ArtGenerationError, ui.ConfigurationError, ValueError) as error:
            self._send_json({"error": str(error)}, 400)

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
            "script-src 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self'; media-src 'self'",
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
