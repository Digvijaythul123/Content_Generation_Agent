"""Upload Reels to a YouTube channel as Shorts (YouTube Data API v3).

A vertical video of three minutes or less is a Short. YouTube takes the file
itself (a resumable upload), so no public media host is needed. Sign in once
with ``python3 -m scripts.youtube_auth``; YOUTUBE_CLIENT_ID,
YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN then live in .env.

Google keeps videos uploaded by a new, unaudited API project private until
the project passes its (free) API compliance audit; until then upload by
hand from YouTube Studio with the text from the review page.
"""

import re
import time

import requests

from app_settings import SettingsError, current_file_setting, get_setting, require_settings


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
# Education; the page teaches.
CATEGORY_ID = "27"
DEFAULT_TAGS = ("Buddha", "Buddhism", "Dhamma", "Buddha teachings", "mindfulness", "meditation")
DESCRIPTION_HASHTAGS = "#Buddha #Buddhism #Dhamma"


class YouTubePublishError(RuntimeError):
    """Raised when YouTube rejects or cannot complete an upload.

    ``transient`` marks network problems and quota limits worth retrying.
    """

    def __init__(self, message, transient=False, rate_limited=False):
        super().__init__(message)
        self.transient = transient or rate_limited
        self.rate_limited = rate_limited


def youtube_configured():
    """True when the YouTube sign-in settings are in .env (not whether valid)."""
    return all(
        get_setting(name)
        for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


def _plain(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or "")).strip()


def default_title(record):
    """The on-screen hook, which is also what makes people stop on Shorts."""
    first_line = next((line for line in _plain(record.get("caption")).splitlines() if line.strip()), "")
    source = record.get("main_point") or record.get("title") or first_line
    title = " ".join(_plain(source).split())
    suffix = " #Shorts"
    limit = TITLE_MAX - len(suffix)
    if len(title) > limit:
        title = title[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return title + suffix


def default_description(record):
    """The caption without its hashtags, then three channel hashtags."""
    lines = [
        line for line in _plain(record.get("caption")).splitlines()
        if not re.fullmatch(r"\s*(#\S+\s*)+", line)
    ]
    body = "\n".join(lines).strip()
    body = re.sub(r"(?:\s#\w+)+\s*$", "", body).strip()
    text = f"{body}\n\n{DESCRIPTION_HASHTAGS}" if body else DESCRIPTION_HASHTAGS
    return text[:DESCRIPTION_MAX]


def youtube_metadata(record):
    """Title, description and tags: the saved ones, or defaults from the post."""
    tags = record.get("youtube_tags")
    if not isinstance(tags, list) or not tags:
        tags = list(DEFAULT_TAGS)
    return {
        "title": (record.get("youtube_title") or "").strip() or default_title(record),
        "description": (record.get("youtube_description") or "").strip() or default_description(record),
        "tags": tags,
    }


def validate_metadata(title, description, tags):
    if not title.strip() or len(title) > TITLE_MAX or "<" in title or ">" in title:
        raise ValueError(f"The YouTube title must be 1-{TITLE_MAX} characters, without < or >.")
    if len(description) > DESCRIPTION_MAX or "<" in description or ">" in description:
        raise ValueError(f"The YouTube description must be under {DESCRIPTION_MAX} characters, without < or >.")
    if sum(len(tag) for tag in tags) > 400:
        raise ValueError("The YouTube tags are too long (400 characters in all).")


class YouTubePublisher:
    def __init__(self, client_id=None, client_secret=None, refresh_token=None, session=None,
                 sleep=time.sleep):
        if not (client_id and client_secret and refresh_token):
            try:
                settings = require_settings(
                    "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"
                )
            except SettingsError as error:
                raise YouTubePublishError(str(error)) from error
            client_id = client_id or settings["YOUTUBE_CLIENT_ID"]
            client_secret = client_secret or settings["YOUTUBE_CLIENT_SECRET"]
            # The sign-in script rewrites .env; read the current token.
            refresh_token = refresh_token or current_file_setting(
                "YOUTUBE_REFRESH_TOKEN", settings["YOUTUBE_REFRESH_TOKEN"]
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._session = session or requests.Session()
        self._sleep = sleep

    def _access_token(self):
        try:
            response = self._session.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
        except requests.RequestException as error:
            raise YouTubePublishError(
                f"Could not reach Google sign-in ({type(error).__name__}).", transient=True
            ) from error
        data = _json(response)
        if response.status_code >= 400 or not data.get("access_token"):
            raise YouTubePublishError(
                "YouTube sign-in failed; run python3 -m scripts.youtube_auth again "
                f"({data.get('error', response.status_code)})."
            )
        return data["access_token"]

    def upload_short(self, path, title, description, tags=(), publish_at=None):
        """Upload an MP4; returns {video_id, url, privacy}.

        With ``publish_at`` (an aware datetime) the video stays private and
        YouTube publishes it at that time.
        """
        validate_metadata(title, description, list(tags))
        status = {
            "privacyStatus": "private" if publish_at else "public",
            "selfDeclaredMadeForKids": False,
            # The art and clips are made with AI tools.
            "containsSyntheticMedia": True,
        }
        if publish_at:
            status["publishAt"] = publish_at.isoformat().replace("+00:00", "Z")
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": list(tags),
                "categoryId": CATEGORY_ID,
                "defaultLanguage": "en",
            },
            "status": status,
        }
        token = self._access_token()
        size = path.stat().st_size
        try:
            start = self._session.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Upload-Content-Length": str(size),
                    "X-Upload-Content-Type": "video/mp4",
                },
                timeout=60,
            )
            _raise_for_error(start)
            location = start.headers.get("Location")
            if not location:
                raise YouTubePublishError("YouTube did not start the upload.", transient=True)
            with path.open("rb") as handle:
                finish = self._session.put(
                    location,
                    data=handle,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(size),
                    },
                    timeout=600,
                )
        except requests.RequestException as error:
            raise YouTubePublishError(
                f"Could not reach YouTube ({type(error).__name__}).", transient=True
            ) from error
        _raise_for_error(finish)
        video = _json(finish)
        if not video.get("id"):
            raise YouTubePublishError("YouTube did not return a video id.", transient=True)
        return {
            "video_id": video["id"],
            "url": f"https://www.youtube.com/shorts/{video['id']}",
            "privacy": (video.get("status") or {}).get("privacyStatus", status["privacyStatus"]),
        }


def _json(response):
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _raise_for_error(response):
    if response.status_code < 400:
        return
    error = _json(response).get("error") or {}
    reasons = {item.get("reason") for item in error.get("errors") or [] if isinstance(item, dict)}
    message = error.get("message") or f"HTTP {response.status_code}"
    if reasons & {"quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}:
        raise YouTubePublishError(f"YouTube limit reached: {message}", rate_limited=True)
    raise YouTubePublishError(
        f"YouTube returned HTTP {response.status_code}: {message}",
        transient=response.status_code >= 500,
    )
