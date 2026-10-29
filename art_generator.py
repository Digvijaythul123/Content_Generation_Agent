import base64
import re
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
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
# Short motion clips (for example from Meta AI) can replace a still image.
MAX_VIDEO_ARTWORK_BYTES = 80 * 1024 * 1024
VIDEO_ARTWORK_SUFFIXES = (".mp4", ".mov")

# Copy is laid over the art later, so the art must be wordless. Image tools
# such as Copilot (DALL-E) tend to paint any words the prompt mentions, even
# in a "no text" list, so these rules never name text, letters, or captions.
_ART_RULES = (
    "Background artwork for a 4:5 portrait Instagram post. "
    "Place the main subject in the right third of the frame. Keep the left "
    "60% calm, softly lit, and empty (plain textured background, nothing "
    "in it). {wordless}"
)
_IMAGE_REEL_ART_RULES = (
    "Background artwork for a 9:16 vertical Instagram Reel. "
    "{composition} {text_area} The camera slowly pushes in, so keep the "
    "subject away from the edges. {wordless}"
)
_FEED_POSTER_ART_RULES = (
    "Background artwork for a 4:5 portrait Instagram post. Place the main "
    "subject in the lower 55% of the frame, large and clear. Keep the upper "
    "40% open, luminous, and uncluttered (open sky, soft mist, or a gentle "
    "beam of light), calm and uncluttered (a moon or soft clouds are fine). {wordless}"
)
_WORDLESS = (
    "A purely pictorial image: every surface is blank and unmarked, with no "
    "writing, signs, symbols, watermark, border, or frame."
)
_ART_RULES = _ART_RULES.format(wordless=_WORDLESS)
_IMAGE_REEL_ART_RULES = _IMAGE_REEL_ART_RULES.replace("{wordless}", _WORDLESS)
_FEED_POSTER_ART_RULES = _FEED_POSTER_ART_RULES.format(wordless=_WORDLESS)
_POSTER_COMPOSITION = (
    "Place the main subject in the lower 55% of the frame, large and clear."
)
_POSTER_TEXT_AREA = (
    "Keep the upper 35% open, luminous, and uncluttered (open sky, soft mist, "
    "or a gentle beam of light), calm and uncluttered (a moon or soft clouds are fine)."
)
_PANEL_COMPOSITION = "Make the main subject large, filling about 60% of the upper frame."
# Every Reel should look like a frame from a high-end film, not a stock image.
_CINEMATIC_QUALITY = (
    "Quality: a cinematic, high-end image with layered depth (foreground, "
    "subject, background), volumetric light and atmospheric perspective, a "
    "rich film-like color grade, crisp fine detail, and a masterful, "
    "uncluttered composition."
)
_TEXT_AREAS = {
    "night": (
        "Let the lower 40% fall into deep, natural, empty shadow."
    ),
    "day": (
        "Keep the lower 40% calm, softly lit, plain, and empty."
    ),
}


def art_aspect_ratio(record):
    return "9:16" if record.get("format_id") == "image_reel" else "4:5"


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


_PROVIDER_KEYS = {"cloudflare": "CLOUDFLARE_AI_TOKEN", "gemini": "GEMINI_API_KEY"}


def art_service_problem():
    """Why automatic artwork can't run, or None when an image service is set up."""
    provider = get_setting("ART_PROVIDER", DEFAULT_ART_PROVIDER).lower()
    key = _PROVIDER_KEYS.get(provider)
    if key is None:
        return f"ART_PROVIDER {provider!r} is not 'cloudflare' or 'gemini'."
    if not (get_setting(key) or "").strip():
        return f"No image service is connected ({key} is empty in .env)."
    return None


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


def visual_style_for(record):
    """Return the post's configured visual style, or None for brand styling."""
    style_id = record.get("visual_style")
    profile_id = record.get("profile_id")
    if not style_id or not profile_id:
        return None
    from config_loader import ConfigurationError, load_profile_visual_styles

    try:
        styles = load_profile_visual_styles(profile_id)
    except ConfigurationError as error:
        raise ArtGenerationError(str(error)) from error
    for style in styles:
        if style["id"] == style_id:
            return style
    raise ArtGenerationError(f"Unknown visual style {style_id!r}.")


# Styles that depict the thinker themself need their real likeness.
_LIKENESS_STYLES = ("living_thinker", "thinker_statue", "painterly")


def _thinker_likeness(record, style):
    """Name the thinker so the image tool uses its own knowledge of them.

    No written descriptions: the user can attach a reference photo in the
    image tool when they want a closer likeness.
    """
    if not style or style["id"] not in _LIKENESS_STYLES:
        return None
    thinker_id = record.get("thinker_id")
    if not thinker_id:
        return None
    from config_loader import ConfigurationError, load_profile_thinkers

    try:
        thinkers = load_profile_thinkers(record.get("profile_id"))
    except ConfigurationError:
        return None
    thinker = next((item for item in thinkers if item["id"] == thinker_id), None)
    if not thinker:
        return None
    alias = thinker.get("art_alias")
    if alias:
        # Some image tools refuse named real people; describe the role only.
        return f"Depict {alias}. If a reference image is attached, match the face from it."
    name = thinker["name"].split(" (")[0]
    form = "as a statue or bust of " if style["id"] == "thinker_statue" else ""
    return (
        f"Depict {form}{name} the way they are widely recognised. If a "
        "reference image is attached, match the face from it."
    )


def _without_blocked_names(text, record):
    """Swap a thinker's name for their art alias when tools refuse the name."""
    thinker_id = record.get("thinker_id")
    if not thinker_id:
        return text
    from config_loader import ConfigurationError, load_profile_thinkers

    try:
        thinkers = load_profile_thinkers(record.get("profile_id"))
    except ConfigurationError:
        return text
    thinker = next((item for item in thinkers if item["id"] == thinker_id), None)
    if not thinker or not thinker.get("art_alias"):
        return text
    names = {thinker["name"], thinker["name"].split(" (")[0]}
    names |= set(re.findall(r"\(([^)]+)\)", thinker["name"]))
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", "the mystic", text)
    return text


_TEXT_SPACE_PATTERN = re.compile(
    r",?\s*(?:to\s+(?:leave|make|keep)\s+(?:room|space)\s+)?for\s+(?:the\s+)?"
    r"(?:text|copy|words|title|caption|lettering)(?:\s+(?:overlay|area|later))?\b",
    re.IGNORECASE,
)


def _setting_lines(record):
    """Place and weather lines that override the scene's own setting."""
    from config_loader import (
        ConfigurationError,
        load_profile_sceneries,
        load_profile_weathers,
    )

    profile_id = record.get("profile_id")
    lines = []
    for field, loader, label in (
        ("scenery", load_profile_sceneries, "Place"),
        ("weather", load_profile_weathers, "Weather and light"),
    ):
        value = record.get(field)
        if not value or not profile_id:
            continue
        try:
            item = next((entry for entry in loader(profile_id) if entry["id"] == value), None)
        except ConfigurationError:
            item = None
        if item:
            lines.append(
                f"{label} (use this even if the scene above says otherwise): "
                f"{item['description']}."
            )
    return lines


def is_designed(record):
    """True for illustrated story modes, where the image tool draws the words.

    Carousels draw their own slides, so they are never designed images.
    """
    if record.get("format_id") == "carousel":
        return False
    subtype = record.get("subtype") or record.get("qa_subtype")
    profile_id = record.get("profile_id")
    if not subtype or not profile_id:
        return False
    from config_loader import ConfigurationError, load_profile_subtypes

    try:
        subtypes = load_profile_subtypes(profile_id)
    except ConfigurationError:
        return False
    return any(
        item.get("id") == subtype and item.get("designed_image") for item in subtypes
    )


def _handle_for(record):
    brand_id = record.get("brand_id")
    if not brand_id:
        return ""
    from config_loader import ConfigurationError, load_brand

    try:
        return load_brand(brand_id).template.handle or ""
    except ConfigurationError:
        return ""


# Lists whose last line is the turn (peace, the final point): a Reel holds
# that line back with the closing line. Speech bubbles stay together.
_LAST_LINE_IS_PAYOFF = ("mind_states", "numbered_list")


def _holds_back_last_line(record):
    return (record.get("subtype") or record.get("qa_subtype")) in _LAST_LINE_IS_PAYOFF


def designed_payoff(record):
    """What an illustrated Reel holds back and fades in later: the last line
    of a list (Mind States, Numbered List) and the closing line."""
    lines = [line.strip() for line in str(record.get("main_point") or "").splitlines() if line.strip()]
    parts = [lines[-1]] if len(lines) > 1 and _holds_back_last_line(record) else []
    if str(record.get("supporting_copy") or "").strip():
        parts.append(str(record["supporting_copy"]).strip())
    return "\n".join(parts)


def _designed_art_prompt(record, scene, style, art_style=None):
    """A finished illustrated post whose words the image tool draws."""
    from content_text import strip_highlights

    reel = art_aspect_ratio(record) == "9:16"
    canvas = "a 9:16 vertical Instagram Reel" if reel else "a 4:5 portrait Instagram post"
    safe_area = (
        "Keep every word in the middle of the frame, clear of the top 12%, "
        "the bottom 22%, and the right 12%, where Instagram's buttons and "
        "caption sit."
        if reel
        else "Keep every word at least 6% away from each edge."
    )
    def plain(value):
        return strip_highlights(str(value or "")).strip()

    def quoted(text):
        # Text that already has quote marks is shown as it is.
        return text if '"' in text or "\u201c" in text else f'"{text}"'

    words = ["Exact words to draw, spelled exactly as written, and no others:"]
    if plain(record.get("title")):
        words.append(f'Headline: {quoted(plain(record["title"]))}')
    lines = [plain(line) for line in str(record.get("main_point") or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) == 1:
        words.append(f"Main line: {quoted(lines[0])}")
    elif lines:
        words.append("Lines, in this order, one per row or panel:")
        words += [f"- {quoted(line)}" for line in lines]
    # In a Reel the closing line is the payoff: the image tool draws it low
    # in the frame, and the video keeps it veiled until the hook has landed.
    payoff_later = reel and bool(designed_payoff(record))
    if plain(record.get("supporting_copy")):
        words.append(f'Closing line: {quoted(plain(record["supporting_copy"]))}')
    handle = _handle_for(record)
    if handle:
        words.append(f'Small handle near the bottom: "{handle}"')
    emphasis = re.findall(
        r"\*\*(.+?)\*\*",
        " ".join(str(record.get(field) or "") for field in ("title", "main_point", "supporting_copy")),
    )
    if emphasis:
        words.append(
            "Make these words bold and in the accent color: "
            + ", ".join(dict.fromkeys(emphasis))
        )
    if payoff_later:
        held = plain(designed_payoff(record).splitlines()[0])
        safe_area += (
            f" Place {quoted(held)} and everything after it in the lower part "
            "of the frame, between 60% and 85% of the height, clearly apart "
            "from the words above (the Reel reveals it a few seconds later)."
        )
    parts = [
        f"Create one finished, illustrated image for {canvas}. The words are "
        f"part of the design. {safe_area}",
        "\n".join(words),
        f"Layout and illustration: {scene}",
        *_setting_lines(record),
    ]
    if style:
        parts.append(f"Visual style: {' '.join(style['recipe'].split())}")
    elif art_style:
        parts.append(f"Visual style: {art_style}")
    likeness = _thinker_likeness(record, style)
    if likeness:
        parts.append(f"Likeness: {likeness}")
    parts.append(
        "Lettering: crisp, evenly spaced, and easy to read on a phone, with "
        "strong contrast against what is behind it. Do not add any other "
        "words, numbers, logos, signatures, or watermarks."
    )
    if style and style.get("avoid"):
        parts.append(f"Avoid: {style['avoid']}.")
    return "\n\n".join(parts)


def build_art_prompt(record, art_style=None):
    description = str(record.get("design_prompt") or "").strip()
    if not description:
        raise ArtGenerationError("The post has no design prompt to paint from.")
    style = visual_style_for(record)
    if is_designed(record):
        return _designed_art_prompt(
            record, _without_blocked_names(description, record), style, art_style
        )
    if art_aspect_ratio(record) == "9:16":
        palette = style.get("palette", "day") if style else "day"
        if record.get("layout") == "poster":
            rules = _IMAGE_REEL_ART_RULES.format(
                composition=_POSTER_COMPOSITION, text_area=_POSTER_TEXT_AREA
            )
        else:
            rules = _IMAGE_REEL_ART_RULES.format(
                composition=_PANEL_COMPOSITION, text_area=_TEXT_AREAS[palette]
            )
        parts = [rules, _CINEMATIC_QUALITY]
    elif record.get("layout") == "poster":
        parts = [_FEED_POSTER_ART_RULES, _CINEMATIC_QUALITY]
    else:
        parts = [_ART_RULES]
    if style:
        parts.append(f"Visual style: {' '.join(style['recipe'].split())}")
    elif art_style:
        parts.append(f"Visual style: {art_style}")
    scene = _without_blocked_names(description, record)
    # The text model sometimes adds "space for text"; image tools then paint
    # lettering, so drop those phrases (the rules above already keep space).
    scene = _TEXT_SPACE_PATTERN.sub("", scene)
    if record.get("layout") == "poster":
        # Older scenes reserved the bottom for text; posters use the top.
        scene = re.sub(
            r"[,;]?\s*(?:with\s+)?(?:the\s+)?(?:lower|bottom)\s+\d+%[^.\n]*",
            "",
            scene,
            flags=re.IGNORECASE,
        )
    parts.append(f"Scene: {scene}")
    parts += _setting_lines(record)
    likeness = _thinker_likeness(record, style)
    if likeness:
        parts.append(f"Likeness: {likeness}")
    if style and style.get("avoid"):
        parts.append(f"Avoid: {style['avoid']}.")
    return "\n\n".join(parts)


# Natural sounds for a Flow (Veo) clip, picked from words in its scene.
_AMBIENCE = (
    (("rain", "monsoon", "storm"), "steady soft rain"),
    (("snow",), "hushed winter quiet with a faint wind"),
    (("river", "stream", "waterfall", "lake", "sea", "ocean", "shore", "waves"), "gentle flowing water"),
    (("forest", "grove", "jungle", "bamboo", "tree"), "leaves rustling and distant birds"),
    (("temple", "monastery", "stupa", "shrine", "bell"), "a distant temple bell"),
    (("night", "moon", "stars", "dusk"), "crickets and a calm night breeze"),
    (("village", "market", "city", "road"), "quiet distant village sounds"),
    (("cave",), "soft echo and dripping water"),
    (("fire", "lamp", "candle"), "a softly crackling flame"),
)

FLOW_CLIP_SECONDS = 10


def _script_lines(script):
    """{'Opening': ..., 'Camera': ...} from a saved video script; the
    on-screen text notes are dropped (words are added after filming)."""
    lines = {}
    for line in str(script or "").splitlines():
        match = re.match(r"\s*(Opening|Middle|Ending|Camera|Sound)\b[^:]*:\s*(.+)", line)
        if match:
            lines[match.group(1)] = re.split(r"\s+On screen", match.group(2))[0].strip()
    return lines


def is_flow_ready(record):
    """True for Reels whose art can become a Flow video: the words are added
    on top later, so the clip itself must stay wordless. Illustrated posts
    carry their words in the art, which video tools would warp."""
    return art_aspect_ratio(record) == "9:16" and not is_designed(record)


# Scene sentences asking for a close-up or a push toward a face: the clip
# then ends with the head filling the frame, under the words on top.
_CLOSE_SHOT = re.compile(
    r"[^.]*\b(close-?up|push(?:es|ing)? (?:in )?(?:toward|towards|into|in on) (?:his|her|the) face|"
    r"zoom(?:s|ing)? (?:in|into|toward)|extreme close)[^.]*\.\s*",
    re.IGNORECASE,
)
_FRAMING = (
    "Framing for the whole 10 seconds: keep it a wide or medium shot; the main "
    "figure's head stays below the middle of the frame and the upper third "
    "stays open sky or mist (the words sit there). Never zoom in to a close-up "
    "of a face."
)


def build_flow_prompt(record):
    """A Google Flow (Veo) prompt that brings the post's still art to life
    as one 10-second vertical shot, to use with the art as its first frame."""
    if record.get("flow_story"):
        # The story script carries the scenes; no still art is needed.
        return build_flow_story_prompt(record)
    description = str(record.get("design_prompt") or "").strip()
    if not description:
        raise ArtGenerationError("The post has no design prompt to film from.")
    if not is_flow_ready(record):
        raise ArtGenerationError(
            "Video clips are for Reels with words added on top; illustrated "
            "posts carry their words in the art and stay as images."
        )
    scene = _TEXT_SPACE_PATTERN.sub("", _without_blocked_names(description, record))
    scene = " ".join(_CLOSE_SHOT.sub(" ", scene).split())
    setting = " ".join(_setting_lines(record))
    words = f"{scene} {setting}".lower()
    sounds = [sound for keys, sound in _AMBIENCE if any(key in words for key in keys)]
    sound = ", ".join(sounds[:2]) or "a soft breeze and distant birds"
    style = visual_style_for(record)
    look = f" Keep the look: {' '.join(style['recipe'].split())}" if style else ""
    still = artwork_path(record["id"]) if record.get("id") else None
    from_image = still is not None and not is_video_artwork(still)
    opening = (
        f"One continuous {FLOW_CLIP_SECONDS}-second vertical 9:16 shot that starts exactly "
        "on the attached image (use it as the first frame). Keep every person, face, "
        "robe, colour, and the light the same as in the image."
        if from_image
        else f"One continuous {FLOW_CLIP_SECONDS}-second vertical 9:16 cinematic shot of "
        "the scene below, photorealistic, softly lit, with the main figure large and "
        "clear in the lower half of the frame."
    )
    script = _script_lines(record.get("video_script"))
    if script:
        beats = " ".join(
            f"{span}: {script[label]}" for label, span in
            (("Opening", "0-3 s"), ("Middle", "3-7 s"), ("Ending", "7-10 s"))
            if script.get(label)
        )
        motion = f"Action, beat by beat (slow, calm, natural): {beats}"
        move = _CLOSE_SHOT.sub("", script.get("Camera") or "").strip() or "A slow, gentle sideways drift."
        camera = f"Camera: {move} No cuts, no shaking, no fast moves. {_FRAMING}"
        sound = f"Sound: natural ambience only: {(script.get('Sound') or sound).rstrip('.')}. No speech, no voice-over, no music, no singing."
    else:
        motion = (
            "Motion: slow, calm, and natural. The main figure stays in place and keeps "
            "doing what the image shows (breathing, a slight turn of the head, a hand "
            "moving gently if they are giving or teaching). Robes, leaves, water, "
            "smoke, and light move softly; weather in the image keeps moving."
        )
        camera = (
            "Camera: a very slight, slow push-in or a gentle sideways drift. No "
            f"cuts, no shaking, no fast moves, no zooming out. {_FRAMING}"
        )
        sound = (
            f"Sound: natural ambience only: {sound}. No speech, no voice-over, no "
            "music, no singing."
        )
    if "buddha" in words:
        # Video tools often draw "the Buddha" as a shaved-head monk.
        opening += (
            " The Buddha appears in his traditional form: tightly curled dark hair "
            "with the rounded crown (ushnisha), long earlobes, a serene face, and "
            "a simple saffron robe over one shoulder; he is not a shaved-head monk. "
            "Monks with him have shaved heads."
        )
    parts = [
        opening + look,
        motion,
        camera,
        sound,
        "Keep the open sky and empty areas of the frame calm and uncluttered "
        "(words are added there later). The video must contain no text, "
        "letters, captions, subtitles, "
        "signs, logos, or watermarks drawn into the scene.",
        "Avoid: new people appearing, faces or bodies changing shape, extra "
        "limbs or fingers, the Buddha laughing or making dramatic gestures, "
        "modern objects.",
        f"Scene, for reference: {scene}",
    ]
    if setting:
        parts.append(setting)
    return "\n\n".join(parts)


_STORY_SCENE = re.compile(
    r"^Scene (\d) \(([^)]*)\):\s*(.*?)\s*(Narrator|Young monk|The buddha|The Buddha):\s*\"(.*)\"\s*$"
)


def build_flow_story_prompt(record):
    """One Google Flow prompt for a whole voiced story Reel: three scenes
    with soft cuts, the exact narration, music, and the Buddha's look."""
    script = str(record.get("video_script") or "")
    scenes, narrator, music = [], None, None
    for line in script.splitlines():
        match = _STORY_SCENE.match(line.strip())
        if match:
            number, span, visual, speaker, spoken = match.groups()
            scenes.append((number, span, visual, speaker, spoken))
        elif line.startswith("Narrator:"):
            narrator = line.split(":", 1)[1].strip().rstrip(".")
        elif line.startswith("Music:"):
            music = line.split(":", 1)[1].strip().rstrip(".")
    if not scenes:
        raise ArtGenerationError("Write the story script first (Write video script).")
    host = bool(record.get("host"))
    dialogue = any(speaker != "Narrator" for _, _, _, speaker, _ in scenes)
    shots = "\n".join(
        f"Shot {number} ({span}): "
        + (re.sub(r"\b([Tt]he host)\b", r"\1 (use my avatar)", _without_blocked_names(visual, record), count=1)
           if host else _without_blocked_names(visual, record))
        + f" {'The Buddha' if speaker.lower() == 'the buddha' else speaker} says: \"{spoken}\""
        for number, span, visual, speaker, spoken in scenes
    )
    if dialogue:
        voice = (
            "Voices: the young monk speaks his line in a light, curious voice and "
            "the Buddha answers in a calm, warm, deep voice; their lips move with "
            "their own words. Speak exactly the lines above, in English, at a "
            f"calm pace that fits the {FLOW_CLIP_SECONDS} seconds; no other speech."
        )
    else:
        voice = (
            f"Voice: {narrator or 'a calm, warm, deep male narrator'}. Speak exactly "
            "the narrator lines above, in English, at a calm pace that fits the "
            f"{FLOW_CLIP_SECONDS} seconds; no other speech, and no one in the scene talks."
        )
        if host:
            voice += " Use my voice for the narrator."
    return "\n\n".join([
        f"A {FLOW_CLIP_SECONDS}-second vertical 9:16 cinematic video, photorealistic, "
        "warm natural light, told in three short shots joined by soft cuts.",
        shots,
        voice,
        f"Music and sound: {music or 'soft bamboo flute and tanpura'}, quiet under the "
        "voice, with gentle natural ambience.",
        "The Buddha appears in his traditional form: tightly curled dark hair with "
        "the rounded crown (ushnisha), long earlobes, a serene face, and a simple "
        "saffron robe over one shoulder; he is a living, breathing man with natural "
        "skin, not a statue or a painting, and not a shaved-head monk; his face "
        "stays the same in every shot. Before his awakening he is Prince Siddhartha: "
        "long dark hair in a topknot, fine white clothes. Monks have shaved heads.",
        ("Shot 1 may be close on the host; the Buddha's shots are wide or medium. "
         "Modern things belong only to the host's shot. "
         if host else "Wide or medium shots, no modern objects. ")
        + "Slow, calm camera moves; no fast action, no dramatic gestures, no faces "
        "changing shape, no extra limbs.",
        "No on-screen text, subtitles, captions, titles, logos, or watermarks.",
    ])


def detect_video_type(data):
    """Recognise MP4 and QuickTime clips by their 'ftyp' box."""
    if data[4:8] != b"ftyp":
        return None
    return "video/quicktime" if data[8:10] == b"qt" else "video/mp4"


def is_video_artwork(path):
    return path is not None and path.suffix.lower() in VIDEO_ARTWORK_SUFFIXES


def artwork_path(post_id):
    """Return the saved artwork for a post, or None when it has none yet."""
    for extension in (".png", ".jpg", ".webp", ".mp4", ".mov"):
        path = GENERATED_ASSETS_DIRECTORY / f"{post_id}_art{extension}"
        if path.is_file():
            return path
    return None


def generate_post_artwork(post_id, art_style=None, client=None):
    """Paint background art for a post and save it beside its other assets."""
    record = load_post(post_id)
    prompt = build_art_prompt(record, art_style)
    image_bytes, _ = (client or get_image_client()).generate(
        prompt, aspect_ratio=art_aspect_ratio(record)
    )
    return save_post_artwork(post_id, image_bytes)


def save_post_artwork(post_id, image_bytes):
    """Validate and store artwork bytes, e.g. from an API or a manual upload.

    One-image Reels may also take a short MP4 or MOV motion clip.
    """
    record = load_post(post_id)
    video_type = detect_video_type(image_bytes)
    if video_type:
        if record.get("format_id") != "image_reel":
            raise ArtGenerationError("Video art is only supported for one-image Reels.")
        if len(image_bytes) > MAX_VIDEO_ARTWORK_BYTES:
            raise ArtGenerationError("Video art must be 80 MB or smaller.")
        mime_type = video_type
    else:
        if len(image_bytes) > MAX_ARTWORK_BYTES:
            raise ArtGenerationError("Artwork must be 15 MB or smaller.")
        mime_type = detect_image_type(image_bytes)
        if mime_type is None:
            raise ArtGenerationError(
                "Artwork must be a PNG, JPEG, or WebP image, or an MP4/MOV clip."
            )
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
