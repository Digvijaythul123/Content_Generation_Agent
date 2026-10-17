import base64
import secrets

import requests

from app_settings import SettingsError, get_setting, require_settings
from post_storage import load_post, save_post
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT


DEFAULT_ART_PROVIDER = "cloudflare"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_CLOUDFLARE_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_CLOUDFLARE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
)
MAX_ARTWORK_BYTES = 15 * 1024 * 1024
_IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

# Text is overlaid later from the approved copy, so the art must have none.
_ART_RULES = (
    "Background artwork for a 4:5 portrait Instagram post. "
    "Place the main subject in the right third of the frame. Keep the left "
    "60% calm, softly lit, and uncluttered (plain textured background) so "
    "text can be overlaid there later. Absolutely no text, letters, numbers, "
    "captions, signatures, watermarks, logos, or frames anywhere in the image."
)


class ArtGenerationError(RuntimeError):
    """Raised when background artwork cannot be generated."""


class GeminiImageClient:
    def __init__(self, api_key=None, model=None, session=None):
        if api_key is None:
            try:
                api_key = require_settings("GEMINI_API_KEY")["GEMINI_API_KEY"]
            except SettingsError as error:
                raise ArtGenerationError(str(error)) from error
        self._api_key = api_key
        self._model = model or get_setting(
            "GEMINI_IMAGE_MODEL", DEFAULT_GEMINI_IMAGE_MODEL
        )
        self._session = session or requests.Session()

    def generate(self, prompt, aspect_ratio="4:5"):
        """Return (image_bytes, mime_type) for one generated image."""
        try:
            response = self._session.post(
                _GEMINI_URL.format(model=self._model),
                headers={"x-goog-api-key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": aspect_ratio},
                    },
                },
                timeout=180,
            )
        except requests.Timeout as error:
            raise ArtGenerationError(
                "Gemini did not return an image within 180 seconds."
            ) from error
        except requests.RequestException as error:
            raise ArtGenerationError(
                f"Could not reach Gemini ({type(error).__name__})."
            ) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") if isinstance(
                payload, dict
            ) else None
            raise ArtGenerationError(
                f"Gemini returned HTTP {response.status_code}: "
                f"{message or 'no error details'}"
            )
        for candidate in payload.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    mime_type = inline.get("mimeType") or inline.get("mime_type")
                    return base64.b64decode(inline["data"]), mime_type or "image/png"
        reason = (
            (payload.get("promptFeedback") or {}).get("blockReason")
            or next(
                (c.get("finishReason") for c in payload.get("candidates") or []),
                None,
            )
        )
        raise ArtGenerationError(
            "Gemini returned no image"
            + (f" (reason: {reason})." if reason else ".")
            + " Try rephrasing the design prompt."
        )


class CloudflareImageClient:
    """Workers AI image generation; Flux Schnell is in the free daily allocation."""

    def __init__(self, api_token=None, account_id=None, model=None, session=None):
        if api_token is None or account_id is None:
            api_token = api_token or get_setting("CLOUDFLARE_AI_TOKEN")
            account_id = account_id or get_setting(
                "CLOUDFLARE_ACCOUNT_ID", get_setting("R2_ACCOUNT_ID")
            )
            missing = [
                name
                for name, value in (
                    ("CLOUDFLARE_AI_TOKEN", api_token),
                    ("CLOUDFLARE_ACCOUNT_ID or R2_ACCOUNT_ID", account_id),
                )
                if not value
            ]
            if missing:
                raise ArtGenerationError(
                    "Missing required settings in .env or the environment: "
                    + ", ".join(missing)
                )
        self._api_token = api_token
        self._account_id = account_id
        self._model = model or get_setting(
            "CLOUDFLARE_IMAGE_MODEL", DEFAULT_CLOUDFLARE_IMAGE_MODEL
        )
        self._session = session or requests.Session()

    def generate(self, prompt, aspect_ratio="4:5"):
        """Return (image_bytes, mime_type); the image is square, cropped later."""
        try:
            response = self._session.post(
                _CLOUDFLARE_URL.format(account_id=self._account_id, model=self._model),
                headers={"Authorization": f"Bearer {self._api_token}"},
                json={
                    "prompt": prompt[:2048],
                    "steps": 8,
                    "seed": secrets.randbelow(2**31 - 1) + 1,
                },
                timeout=180,
            )
        except requests.Timeout as error:
            raise ArtGenerationError(
                "Cloudflare did not return an image within 180 seconds."
            ) from error
        except requests.RequestException as error:
            raise ArtGenerationError(
                f"Could not reach Cloudflare ({type(error).__name__})."
            ) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code >= 400 or payload.get("success") is False:
            errors = payload.get("errors") or []
            message = "; ".join(
                str(error.get("message", error)) if isinstance(error, dict) else str(error)
                for error in errors
            )
            raise ArtGenerationError(
                f"Cloudflare returned HTTP {response.status_code}: "
                f"{message or 'no error details'}"
            )
        result = payload.get("result") or payload
        image = result.get("image") if isinstance(result, dict) else None
        if not image:
            raise ArtGenerationError("Cloudflare returned no image.")
        data = base64.b64decode(image)
        return data, detect_image_type(data) or "image/jpeg"


def get_image_client():
    provider = get_setting("ART_PROVIDER", DEFAULT_ART_PROVIDER).lower()
    if provider == "cloudflare":
        return CloudflareImageClient()
    if provider == "gemini":
        return GeminiImageClient()
    raise ArtGenerationError(
        f"Unknown ART_PROVIDER {provider!r}; use 'cloudflare' or 'gemini'."
    )


def detect_image_type(data):
    for signature, mime_type in _IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return mime_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_art_prompt(record, art_style=None):
    description = str(record.get("design_prompt") or "").strip()
    if not description:
        raise ArtGenerationError("The post has no design prompt to paint from.")
    parts = [_ART_RULES]
    if art_style:
        parts.append(f"Visual style: {art_style}")
    parts.append(f"Scene: {description}")
    return "\n\n".join(parts)


def artwork_path(post_id):
    """Return the saved artwork for a post, or None when it has none yet."""
    for extension in (".png", ".jpg", ".webp"):
        path = GENERATED_ASSETS_DIRECTORY / f"{post_id}_art{extension}"
        if path.is_file():
            return path
    return None


def generate_post_artwork(post_id, art_style=None, client=None):
    """Paint background art for a post and save it beside its other assets."""
    prompt = build_art_prompt(load_post(post_id), art_style)
    image_bytes, _ = (client or get_image_client()).generate(prompt)
    return save_post_artwork(post_id, image_bytes)


def save_post_artwork(post_id, image_bytes):
    """Validate and store artwork bytes, e.g. from an API or a manual upload."""
    if len(image_bytes) > MAX_ARTWORK_BYTES:
        raise ArtGenerationError("Artwork must be 15 MB or smaller.")
    mime_type = detect_image_type(image_bytes)
    if mime_type is None:
        raise ArtGenerationError("Artwork must be a PNG, JPEG, or WebP image.")
    record = load_post(post_id)
    extension = _EXTENSIONS[mime_type]
    GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    previous = artwork_path(post_id)
    output = GENERATED_ASSETS_DIRECTORY / f"{post_id}_art{extension}"
    output.write_bytes(image_bytes)
    if previous is not None and previous != output:
        previous.unlink(missing_ok=True)
    try:
        record["artwork_path"] = str(output.relative_to(PROJECT_ROOT))
    except ValueError:
        record["artwork_path"] = str(output)
    save_post(post_id, record)
    return output
