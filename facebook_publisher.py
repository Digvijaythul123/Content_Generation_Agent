"""Publish one-image Reels to a Facebook Page with the Reels Publishing API.

The video is uploaded straight from this computer (no public hosting):
start an upload session, send the MP4 bytes, then finish and publish.
See https://developers.facebook.com/docs/video-api/guides/reels-publishing
"""

import time

import requests

from app_settings import SettingsError, get_setting, require_settings


DEFAULT_GRAPH_BASE_URL = "https://graph.facebook.com/v23.0"
DEFAULT_UPLOAD_BASE_URL = "https://rupload.facebook.com/video-upload/v23.0"


class FacebookPublishError(RuntimeError):
    """Raised when Facebook rejects or cannot complete a Reel upload.

    ``transient`` marks network problems that are worth retrying.
    """

    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


def facebook_configured():
    """True when a Page ID and Page token are in .env (not whether valid)."""
    return bool(get_setting("FACEBOOK_PAGE_ID") and get_setting("FACEBOOK_PAGE_TOKEN"))


class FacebookPublisher:
    def __init__(
        self,
        page_id=None,
        page_token=None,
        session=None,
        sleep=time.sleep,
        poll_interval_seconds=3,
        poll_timeout_seconds=180,
    ):
        if page_id is None or page_token is None:
            try:
                settings = require_settings("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN")
            except SettingsError as error:
                raise FacebookPublishError(str(error)) from error
            page_id = page_id or settings["FACEBOOK_PAGE_ID"]
            page_token = page_token or settings["FACEBOOK_PAGE_TOKEN"]
        self._page_id = page_id
        self._token = page_token
        self._base_url = get_setting(
            "FACEBOOK_GRAPH_BASE_URL", DEFAULT_GRAPH_BASE_URL
        ).rstrip("/")
        self._upload_url = get_setting(
            "FACEBOOK_UPLOAD_BASE_URL", DEFAULT_UPLOAD_BASE_URL
        ).rstrip("/")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds

    def _call(self, method, url, timeout=60, **kwargs):
        try:
            response = self._session.request(method, url, timeout=timeout, **kwargs)
        except requests.Timeout as error:
            raise FacebookPublishError(
                f"Facebook did not respond within {timeout} seconds.", transient=True
            ) from error
        except requests.RequestException as error:
            # The request may carry the token, so do not echo the error.
            raise FacebookPublishError(
                f"Could not reach Facebook ({type(error).__name__}).", transient=True
            ) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or (isinstance(payload, dict) and "error" in payload):
            details = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = details.get("error_user_msg") or details.get("message")
            raise FacebookPublishError(
                f"Facebook returned HTTP {response.status_code}: "
                f"{message or 'no error details'}"
            )
        if not isinstance(payload, dict):
            raise FacebookPublishError("Facebook returned an unexpected response.")
        return payload

    def _graph(self, method, path, **params):
        params["access_token"] = self._token
        url = f"{self._base_url}/{path}"
        if method == "GET":
            return self._call("GET", url, params=params)
        return self._call("POST", url, data=params)

    def page_info(self):
        """The connected Page's ID, name, and link (no side effects)."""
        return self._graph("GET", self._page_id, fields="id,name,link")

    def publish_reel(self, video_path, description):
        """Upload an MP4 and publish it as a Reel; return its ID and link."""
        started = self._graph("POST", f"{self._page_id}/video_reels", upload_phase="start")
        video_id = started.get("video_id")
        if not video_id:
            raise FacebookPublishError("Facebook did not return a video ID.")
        data = video_path.read_bytes()
        self._call(
            "POST",
            started.get("upload_url") or f"{self._upload_url}/{video_id}",
            timeout=300,
            headers={
                "Authorization": f"OAuth {self._token}",
                "offset": "0",
                "file_size": str(len(data)),
            },
            data=data,
        )
        self._graph(
            "POST",
            f"{self._page_id}/video_reels",
            upload_phase="finish",
            video_id=video_id,
            video_state="PUBLISHED",
            description=description,
        )
        self._wait_until_published(video_id)
        info = self._graph("GET", video_id, fields="permalink_url")
        link = info.get("permalink_url") or ""
        if link.startswith("/"):
            link = f"https://www.facebook.com{link}"
        return {"video_id": video_id, "permalink": link or None}

    def _wait_until_published(self, video_id):
        waited = 0
        while True:
            status = self._graph("GET", video_id, fields="status").get("status", {})
            phase = status.get("publishing_phase", {}) or {}
            processing = status.get("processing_phase", {}) or {}
            if status.get("video_status") == "error" or "error" in (
                phase.get("status"), processing.get("status")
            ):
                errors = phase.get("errors") or processing.get("errors") or []
                detail = errors[0].get("message") if errors else "processing failed"
                raise FacebookPublishError(f"Facebook could not publish the Reel: {detail}")
            if phase.get("status") == "complete" or status.get("video_status") in (
                "ready", "published"
            ):
                return
            if waited >= self._poll_timeout_seconds:
                # Facebook keeps processing; the Reel appears when it is done.
                return
            self._sleep(self._poll_interval_seconds)
            waited += self._poll_interval_seconds
