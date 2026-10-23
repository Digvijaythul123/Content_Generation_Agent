import time

import requests

from app_settings import (
    SettingsError,
    current_file_setting,
    get_setting,
    require_settings,
)


DEFAULT_GRAPH_BASE_URL = "https://graph.instagram.com/v23.0"
_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"


class InstagramPublishError(RuntimeError):
    """Raised when Instagram rejects or cannot complete a publish request.

    ``transient`` marks network problems (no connection, no reply in time)
    that are worth retrying, unlike a rejected token or media.
    """

    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


class InstagramPublisher:
    """Publish media with the Instagram API with Instagram Login.

    Flow: create a media container from a public URL, wait for Instagram to
    process it, then publish the container to the account.
    """

    def __init__(
        self,
        access_token=None,
        account_id=None,
        base_url=None,
        session=None,
        sleep=time.sleep,
        poll_interval_seconds=3,
        poll_timeout_seconds=120,
    ):
        if access_token is None or account_id is None:
            try:
                settings = require_settings(
                    "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID"
                )
            except SettingsError as error:
                raise InstagramPublishError(str(error)) from error
            access_token = access_token or current_file_setting(
                "INSTAGRAM_ACCESS_TOKEN", settings["INSTAGRAM_ACCESS_TOKEN"]
            )
            account_id = account_id or settings["INSTAGRAM_ACCOUNT_ID"]
        self._access_token = access_token
        self._account_id = account_id
        self._base_url = (
            base_url
            or get_setting("INSTAGRAM_GRAPH_BASE_URL", DEFAULT_GRAPH_BASE_URL)
        ).rstrip("/")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds

    def recent_media(self, limit=10):
        """The account's latest posts, newest first (caption and timestamp)."""
        data = self._request(
            "GET",
            f"{self._base_url}/{self._account_id}/media",
            fields="id,caption,timestamp,permalink",
            limit=limit,
        )
        return data.get("data", [])

    def _request(self, method, url, **params):
        params["access_token"] = self._access_token
        try:
            if method == "GET":
                response = self._session.get(url, params=params, timeout=60)
            else:
                response = self._session.post(url, data=params, timeout=60)
        except requests.Timeout as error:
            raise InstagramPublishError(
                "Instagram did not respond within 60 seconds.", transient=True
            ) from error
        except requests.RequestException as error:
            # The URL may contain the access token, so do not echo the error.
            raise InstagramPublishError(
                f"Could not reach Instagram ({type(error).__name__}).",
                transient=True,
            ) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or "error" in payload:
            details = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = details.get("error_user_msg") or details.get("message")
            raise InstagramPublishError(
                f"Instagram returned HTTP {response.status_code}: "
                f"{message or 'no error details'}"
            )
        if not isinstance(payload, dict):
            raise InstagramPublishError("Instagram returned an unexpected response.")
        return payload

    def account_info(self):
        """Return the connected account's ID and username (no side effects)."""
        return self._request(
            "GET", f"{self._base_url}/me", fields="user_id,username,account_type"
        )

    def publishing_quota(self):
        """Return (used, total) posts for the rolling 24-hour window."""
        payload = self._request(
            "GET",
            f"{self._base_url}/{self._account_id}/content_publishing_limit",
            fields="quota_usage,config",
        )
        entries = payload.get("data") or [{}]
        used = int(entries[0].get("quota_usage", 0))
        total = int(entries[0].get("config", {}).get("quota_total", 100))
        return used, total

    def create_image_container(self, image_url, caption):
        payload = self._request(
            "POST",
            f"{self._base_url}/{self._account_id}/media",
            image_url=image_url,
            caption=caption,
            is_ai_generated="true",
        )
        container_id = payload.get("id")
        if not container_id:
            raise InstagramPublishError("Instagram did not return a container ID.")
        return container_id

    def create_reel_container(
        self, video_url, caption, thumb_offset_ms=None, cover_url=None
    ):
        params = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            # Every post here uses AI-generated art: apply Instagram's AI label.
            "is_ai_generated": "true",
        }
        if cover_url:
            # A custom cover image wins over a frame picked from the video.
            params["cover_url"] = cover_url
        elif thumb_offset_ms is not None:
            params["thumb_offset"] = str(int(thumb_offset_ms))
        payload = self._request(
            "POST", f"{self._base_url}/{self._account_id}/media", **params
        )
        container_id = payload.get("id")
        if not container_id:
            raise InstagramPublishError("Instagram did not return a container ID.")
        return container_id

    def wait_until_ready(self, container_id, timeout_seconds=None):
        timeout_seconds = timeout_seconds or self._poll_timeout_seconds
        waited = 0
        while True:
            status = self._request(
                "GET", f"{self._base_url}/{container_id}", fields="status_code"
            ).get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return status
            if status in ("ERROR", "EXPIRED"):
                raise InstagramPublishError(
                    f"Instagram could not process the media (status {status}). "
                    "Check that the media is a public JPEG or MP4 URL."
                )
            if waited >= timeout_seconds:
                raise InstagramPublishError(
                    f"Instagram was still processing the media after "
                    f"{timeout_seconds} seconds."
                )
            self._sleep(self._poll_interval_seconds)
            waited += self._poll_interval_seconds

    def publish_container(self, container_id):
        payload = self._request(
            "POST",
            f"{self._base_url}/{self._account_id}/media_publish",
            creation_id=container_id,
        )
        media_id = payload.get("id")
        if not media_id:
            raise InstagramPublishError("Instagram did not return a media ID.")
        return media_id

    def permalink(self, media_id):
        return self._request(
            "GET", f"{self._base_url}/{media_id}", fields="permalink"
        ).get("permalink")

    def _check_quota(self):
        used, total = self.publishing_quota()
        if used >= total:
            raise InstagramPublishError(
                f"The Instagram publishing limit is reached ({used}/{total} "
                "posts in the last 24 hours). Try again later."
            )

    def _finish(self, container_id, timeout_seconds=None):
        self.wait_until_ready(container_id, timeout_seconds)
        media_id = self.publish_container(container_id)
        try:
            details = self._request(
                "GET",
                f"{self._base_url}/{media_id}",
                fields="permalink,is_ai_generated",
            )
        except InstagramPublishError:
            details = {}  # The post is live; missing details are not fatal.
        return {
            "media_id": media_id,
            "permalink": details.get("permalink"),
            "ai_label": details.get("is_ai_generated"),
        }

    def publish_reel(self, video_url, caption, thumb_offset_ms=None, cover_url=None):
        """Publish one Reel (shared to the feed) and return its ID and link."""
        self._check_quota()
        container_id = self.create_reel_container(
            video_url, caption, thumb_offset_ms, cover_url
        )
        # Instagram transcodes video, which takes much longer than images.
        return self._finish(container_id, timeout_seconds=600)

    def publish_image(self, image_url, caption):
        """Publish one image post and return its ID, link, and AI label."""
        self._check_quota()
        container_id = self.create_image_container(image_url, caption)
        return self._finish(container_id)

    def publish_carousel(self, image_urls, caption):
        """Publish a carousel (2-10 images) and return its ID, link, and AI label.

        Each image becomes a carousel item container; the parent container
        carries the caption, and publishing it posts the whole set.
        """
        if not 2 <= len(image_urls) <= 10:
            raise InstagramPublishError("A carousel needs 2 to 10 images.")
        self._check_quota()
        children = []
        for image_url in image_urls:
            payload = self._request(
                "POST",
                f"{self._base_url}/{self._account_id}/media",
                image_url=image_url,
                is_carousel_item="true",
                is_ai_generated="true",
            )
            child_id = payload.get("id")
            if not child_id:
                raise InstagramPublishError("Instagram did not return a slide container ID.")
            children.append(child_id)
        for child_id in children:
            self.wait_until_ready(child_id)
        payload = self._request(
            "POST",
            f"{self._base_url}/{self._account_id}/media",
            media_type="CAROUSEL",
            children=",".join(children),
            caption=caption,
        )
        container_id = payload.get("id")
        if not container_id:
            raise InstagramPublishError("Instagram did not return a carousel container ID.")
        return self._finish(container_id)

    def refresh_access_token(self):
        """Extend a long-lived token; returns (token, expires_in_seconds)."""
        payload = self._request(
            "GET", _REFRESH_URL, grant_type="ig_refresh_token"
        )
        token = payload.get("access_token")
        if not token:
            raise InstagramPublishError("Instagram did not return a new token.")
        return token, payload.get("expires_in")
