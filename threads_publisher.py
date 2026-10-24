"""Publish Reels, images, and carousels to a Threads account (Threads API).

Like Instagram, Threads fetches media from a public URL: create a container
(video, image, or a carousel of image items), wait until it is ready, then
publish it. See https://developers.facebook.com/docs/threads/posts
"""

import time

import requests

from app_settings import SettingsError, current_file_setting, get_setting, require_settings


DEFAULT_THREADS_BASE_URL = "https://graph.threads.net/v1.0"
_REFRESH_URL = "https://graph.threads.net/refresh_access_token"
THREADS_MAX_CHARACTERS = 500


class ThreadsPublishError(RuntimeError):
    """Raised when Threads rejects or cannot complete a post.

    ``transient`` marks network problems and rate limits worth retrying.
    """

    def __init__(self, message, transient=False, rate_limited=False):
        super().__init__(message)
        self.transient = transient or rate_limited
        self.rate_limited = rate_limited


_RATE_LIMIT_CODES = {4, 17, 32, 613}


def threads_configured():
    """True when a Threads token and user ID are in .env (not whether valid)."""
    return bool(get_setting("THREADS_ACCESS_TOKEN") and get_setting("THREADS_USER_ID"))


class ThreadsPublisher:
    def __init__(
        self,
        access_token=None,
        user_id=None,
        session=None,
        sleep=time.sleep,
        poll_interval_seconds=5,
        poll_timeout_seconds=300,
    ):
        if access_token is None or user_id is None:
            try:
                settings = require_settings("THREADS_ACCESS_TOKEN", "THREADS_USER_ID")
            except SettingsError as error:
                raise ThreadsPublishError(str(error)) from error
            # The scheduler rotates the token in .env; read the current one.
            access_token = access_token or current_file_setting(
                "THREADS_ACCESS_TOKEN", settings["THREADS_ACCESS_TOKEN"]
            )
            user_id = user_id or settings["THREADS_USER_ID"]
        self._token = access_token
        self._user_id = user_id
        self._base_url = get_setting(
            "THREADS_BASE_URL", DEFAULT_THREADS_BASE_URL
        ).rstrip("/")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds

    def _request(self, method, url, **params):
        params["access_token"] = self._token
        try:
            if method == "GET":
                response = self._session.get(url, params=params, timeout=60)
            else:
                response = self._session.post(url, data=params, timeout=60)
        except requests.Timeout as error:
            raise ThreadsPublishError(
                "Threads did not respond within 60 seconds.", transient=True
            ) from error
        except requests.RequestException as error:
            # The request carries the token, so do not echo the error.
            raise ThreadsPublishError(
                f"Could not reach Threads ({type(error).__name__}).", transient=True
            ) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or (isinstance(payload, dict) and "error" in payload):
            details = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = details.get("error_user_msg") or details.get("message")
            raise ThreadsPublishError(
                f"Threads returned HTTP {response.status_code}: {message or 'no error details'}",
                rate_limited=details.get("code") in _RATE_LIMIT_CODES,
            )
        if not isinstance(payload, dict):
            raise ThreadsPublishError("Threads returned an unexpected response.")
        return payload

    def profile(self):
        """The connected account's ID and username (no side effects)."""
        return self._request("GET", f"{self._base_url}/me", fields="id,username")

    def _container(self, **params):
        payload = self._request("POST", f"{self._base_url}/{self._user_id}/threads", **params)
        if not payload.get("id"):
            raise ThreadsPublishError("Threads did not return a container ID.")
        return payload["id"]

    def _wait_until_ready(self, container_id):
        waited = 0
        while True:
            status = self._request(
                "GET", f"{self._base_url}/{container_id}", fields="status,error_message"
            )
            state = status.get("status")
            if state == "FINISHED":
                return
            if state in ("ERROR", "EXPIRED"):
                raise ThreadsPublishError(
                    f"Threads could not process the media: {status.get('error_message') or state}"
                )
            if waited >= self._poll_timeout_seconds:
                raise ThreadsPublishError(
                    "Threads is still processing the media; try again later.", transient=True
                )
            self._sleep(self._poll_interval_seconds)
            waited += self._poll_interval_seconds

    def _publish(self, container_id):
        self._wait_until_ready(container_id)
        payload = self._request(
            "POST", f"{self._base_url}/{self._user_id}/threads_publish", creation_id=container_id
        )
        media_id = payload.get("id")
        if not media_id:
            raise ThreadsPublishError("Threads did not return a post ID.")
        try:
            link = self._request(
                "GET", f"{self._base_url}/{media_id}", fields="permalink"
            ).get("permalink")
        except ThreadsPublishError:
            link = None
        return {"media_id": media_id, "permalink": link}

    def publish_video(self, video_url, text):
        return self._publish(self._container(media_type="VIDEO", video_url=video_url, text=text))

    def publish_image(self, image_url, text):
        return self._publish(self._container(media_type="IMAGE", image_url=image_url, text=text))

    def publish_carousel(self, image_urls, text):
        """Post 2-20 images as one carousel."""
        if len(image_urls) < 2:
            return self.publish_image(image_urls[0], text)
        children = [
            self._container(media_type="IMAGE", image_url=url, is_carousel_item="true")
            for url in image_urls
        ]
        for child in children:
            self._wait_until_ready(child)
        return self._publish(
            self._container(media_type="CAROUSEL", children=",".join(children), text=text)
        )

    def refresh_access_token(self):
        """Extend the long-lived token; returns (token, expires_in_seconds)."""
        payload = self._request("GET", _REFRESH_URL, grant_type="th_refresh_token")
        token = payload.get("access_token")
        if not token:
            raise ThreadsPublishError("Threads did not return a new token.")
        return token, payload.get("expires_in")
