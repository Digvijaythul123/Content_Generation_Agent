import base64
import json
from html import escape
import mimetypes
import re
from string import Template

from dataclasses import replace
from functools import lru_cache

import subprocess
import tempfile
from pathlib import Path

from art_generator import (
    ArtGenerationError,
    artwork_path,
    is_designed,
    is_video_artwork,
    visual_style_for,
)
from config_loader import load_brand
from content_models import BrandTemplate
from post_storage import load_post, save_post
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT


TEMPLATE_DIRECTORY = PROJECT_ROOT / "templates"
INSTAGRAM_FEED_TEMPLATE = TEMPLATE_DIRECTORY / "instagram_feed.html"
_LAYOUT_TEMPLATES = {
    "classic": INSTAGRAM_FEED_TEMPLATE,
    "quote_painting": TEMPLATE_DIRECTORY / "quote_painting.html",
}
IMAGE_REEL_TEMPLATE = TEMPLATE_DIRECTORY / "image_reel.html"
IMAGE_REEL_POSTER_TEMPLATE = TEMPLATE_DIRECTORY / "image_reel_poster.html"
FEED_POSTER_TEMPLATE = TEMPLATE_DIRECTORY / "feed_poster.html"
# Illustrated story modes: the art already carries the words.
DESIGNED_TEMPLATE = TEMPLATE_DIRECTORY / "designed.html"
# "poster" puts the words over open sky in the top third; "panel" uses a
# dark band at the bottom. Records without a layout keep the panel look.
IMAGE_REEL_LAYOUTS = ("poster", "panel")
IMAGE_REEL_SIZE = (1080, 1920)
_RENDERABLE_FORMATS = ("single_page", "image_reel", "carousel")
CAROUSEL_TEMPLATE = TEMPLATE_DIRECTORY / "carousel_slide.html"
# Instagram's API takes up to 10 items in one carousel (cover + 8 + closing).
MAX_CAROUSEL_SLIDES = 10
# Dark cinematic art needs light text on a deep shadow wash.
_NIGHT_COLORS = {"background": "#0E0C0B", "text": "#F5F1E8", "accent": "#F5C542"}
_HIGHLIGHT_PATTERN = re.compile(r"\*\*(.+?)\*\*")
INSTAGRAM_FEED_SIZE = (1080, 1350)
_REQUIRED_FIELDS = ("title", "main_point", "supporting_copy")


class MediaRenderError(RuntimeError):
    """Raised when a post image cannot be rendered."""


def post_image_path(post_id):
    return GENERATED_ASSETS_DIRECTORY / f"{post_id}_instagram.jpg"


def layout_for(brand):
    return brand.template.layout if brand is not None else "classic"


def _curly_quotes(text):
    """Typeset straight double quotes as curly ones (“…”)."""
    return re.sub(r'"([^"]*)"', "\u201c\\1\u201d", text)


def _copy_html(text):
    """Escape copy and render **keyword** markers as highlighted words."""
    text = _curly_quotes(text)
    marked = _HIGHLIGHT_PATTERN.sub(
        lambda match: f"\0{match.group(1)}\1", text.strip()
    ).replace("**", "")
    return (
        escape(marked)
        .replace("\0", '<span class="hl">')
        .replace("\1", "</span>")
    )


def _rgba(hex_colour, alpha):
    red, green, blue = (int(hex_colour[index:index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _art_html(artwork):
    if artwork is None:
        return ""
    mime_type = mimetypes.guess_type(artwork.name)[0] or "image/png"
    try:
        encoded = base64.b64encode(artwork.read_bytes()).decode("ascii")
    except OSError as error:
        raise MediaRenderError(f"Could not read artwork {artwork}: {error}") from error
    return f'<img class="art" alt="" src="data:{mime_type};base64,{encoded}">'


_SOURCE_PATTERN = re.compile(
    r"^(?:Teaching|Idea|Source):\s*(.+)$", re.IGNORECASE | re.MULTILINE
)


def source_line(record):
    """Return the short reference from the caption's Teaching/Source line."""
    match = _SOURCE_PATTERN.search(str(record.get("caption") or ""))
    if not match:
        return ""
    text = match.group(1).strip().rstrip(".;, ")
    reference = re.search(r"\(([^()]+)\)$", text)
    if reference:
        text = reference.group(1)
    # "(Source: Discourses 2.17)" and "(Reference: ...)" keep just the citation.
    return re.sub(r"^(?:source|reference)s?:\s*", "", text.strip(), flags=re.I)


def _footer_text(record, handle):
    # A quiz must not print its answer's source on the image.
    source = "" if record.get("subtype") == "real_or_fake" else source_line(record)
    # Quote posts already show the source in their attribution line.
    if source and source.lower() in str(record.get("supporting_copy") or "").lower():
        source = ""
    return " · ".join(part for part in (source, handle) if part)


def _brand_for(record):
    brand_id = record.get("brand_id")
    if not brand_id:
        return None
    return load_brand(brand_id)


# Average brightness (0-255) of the art behind poster text: above LIGHT the
# text turns dark; between MID and LIGHT the shade behind it gets stronger.
TONE_LIGHT = 150
TONE_MID = 105
# How much a weather look brightens or darkens the art (see the templates),
# so the text tone follows the repainted image, not the original.
LOOK_BRIGHTNESS = {
    "golden_hour": 1.0, "overcast": 0.85, "monsoon_rain": 0.45,
    "after_rain": 0.85, "misty_morning": 1.15, "snowfall": 1.0,
    "blue_hour": 0.5, "moonlit_night": 0.35, "storm_clouds": 0.45,
    "lamplight": 0.5,
}


def weather_look(record):
    """The weather to repaint existing art with, or None."""
    weather = record.get("weather")
    return weather if record.get("weather_look") and weather in LOOK_BRIGHTNESS else None


@lru_cache(maxsize=32)
def _region_brightness(path, modified, size, region):
    """Average luminance of a region of the art as the page crops it."""
    width, height = size
    left, top, region_width, region_height = region
    # Match the poster's crop: cover the frame, then zoom 1.11 from the top.
    zoom_w, zoom_h = round(width * 1.11), round(height * 1.11)
    result = subprocess.run(
        [ffmpeg_executable(), "-loglevel", "error", "-i", path, "-vf",
         f"scale={width}:{height}:force_original_aspect_ratio=increase,"
         f"crop={width}:{height}:(iw-{width})/2:ih-{height},"
         f"scale={zoom_w}:{zoom_h},crop={width}:{height}:(iw-{width})/2:0,"
         f"crop={region_width}:{region_height}:{left}:{top},"
         "scale=1:1:flags=area,format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if result.returncode or not result.stdout:
        return None
    return result.stdout[0]


PLACEMENT_SCRIPT = TEMPLATE_DIRECTORY / "placement.js"
# Rows of the image measured for placement (more rows = finer positions).
_PLACEMENT_ROWS = 96


@lru_cache(maxsize=32)
def _row_profile(path, modified, size):
    """Per-row busyness (edge detail across the text width) and brightness of
    the art as the page shows it; None when the art cannot be read."""
    width, height = size
    zoom_w, zoom_h = round(width * 1.11), round(height * 1.11)
    columns = 64
    result = subprocess.run(
        [ffmpeg_executable(), "-loglevel", "error", "-i", path, "-vf",
         f"scale={width}:{height}:force_original_aspect_ratio=increase,"
         f"crop={width}:{height}:(iw-{width})/2:ih-{height},"
         f"scale={zoom_w}:{zoom_h},crop={width}:{height}:(iw-{width})/2:0,"
         f"scale={columns}:{_PLACEMENT_ROWS}:flags=area,format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    pixels = result.stdout
    if result.returncode or len(pixels) < columns * _PLACEMENT_ROWS:
        return None
    grid = [pixels[row * columns:(row + 1) * columns] for row in range(_PLACEMENT_ROWS)]
    span = range(6, columns - 6)  # the text's width, not the far edges
    busy, lum = [], []
    for row in range(_PLACEMENT_ROWS):
        line = grid[row]
        below = grid[min(row + 1, _PLACEMENT_ROWS - 1)]
        across = sum(abs(line[x + 1] - line[x]) for x in span) / len(span)
        down = sum(abs(below[x] - line[x]) for x in span) / len(span)
        busy.append(round((across + down) / 255, 4))
        lum.append(round(sum(line[x] for x in span) / len(span), 1))
    return tuple(busy), tuple(lum)


def placement_script(artwork, record, size):
    """The inline script that moves the words to the calmest band."""
    try:
        code = PLACEMENT_SCRIPT.read_text(encoding="utf-8")
    except OSError:
        return ""
    profile = None
    if artwork is not None:
        try:
            profile = _row_profile(str(artwork), artwork.stat().st_mtime, size)
        except (OSError, MediaRenderError):
            profile = None
    data = "null"
    if profile:
        data = json.dumps({
            "busy": profile[0], "lum": profile[1], "height": size[1],
            "factor": LOOK_BRIGHTNESS.get(weather_look(record), 1.0),
            "light": TONE_LIGHT, "mid": TONE_MID,
        })
    return f"<script>window.PLACEMENT = {data};\n{code}</script>"


def text_tone(artwork, record):
    """'light', 'mid', or 'dark' for the art behind a poster's words."""
    if artwork is None:
        return "dark"
    if is_image_reel(record):
        size, region = IMAGE_REEL_SIZE, (90, 250, 900, 640)
    else:
        size, region = INSTAGRAM_FEED_SIZE, (80, 90, 920, 520)
    try:
        brightness = _region_brightness(
            str(artwork), artwork.stat().st_mtime, size, region
        )
    except (OSError, MediaRenderError):
        return "dark"
    if brightness is None:
        return "dark"
    brightness *= LOOK_BRIGHTNESS.get(weather_look(record), 1.0)
    if brightness > TONE_LIGHT:
        return "light"
    return "mid" if brightness > TONE_MID else "dark"


def series_label(record):
    """'Day 4 of 30' for posts in the profile's series, else ''."""
    number = record.get("series_number")
    if not number:
        return ""
    length = record.get("series_length")
    return f"Day {number} of {length}" if length else f"Day {number}"


END_CARD_TEMPLATE = TEMPLATE_DIRECTORY / "end_card.html"


def build_end_card_html(record, brand, artwork):
    """The Reel's closing card: near-black, the closing line, the handle."""
    template = brand.template if brand is not None else BrandTemplate()
    try:
        source = END_CARD_TEMPLATE.read_text(encoding="utf-8")
    except OSError as error:
        raise MediaRenderError(f"Could not read {END_CARD_TEMPLATE}: {error}") from error
    return Template(source).substitute(
        art=_art_html(artwork) if artwork is not None else "",
        cta=_copy_html(str(record.get("cta") or "")),
        handle=escape(template.handle or ""),
    )


def is_carousel(record):
    return record.get("format_id") == "carousel"


def carousel_slide_path(post_id, number):
    """Slide 1 is the usual post image; later slides sit beside it."""
    if number == 1:
        return post_image_path(post_id)
    return GENERATED_ASSETS_DIRECTORY / f"{post_id}_slide_{number:02}.jpg"


_NUMBERED_LINE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")


def carousel_slides(record):
    """The slides in order: cover, one per line of ``slides``, closing."""
    lines = [line.strip() for line in str(record.get("slides") or "").splitlines() if line.strip()]
    lines = lines[: MAX_CAROUSEL_SLIDES - 2]
    total = len(lines) + 2
    slides = [{
        "kind": "cover", "big": record.get("title") or "", "small": record.get("main_point") or "",
        "number": "", "counter": "", "hint": "Swipe \u2192",
    }]
    for index, line in enumerate(lines, start=2):
        numbered = _NUMBERED_LINE.match(line)
        slides.append({
            "kind": "inner",
            "big": numbered.group(2) if numbered else line,
            "small": "",
            "number": numbered.group(1).zfill(2) if numbered else "",
            "counter": f"{index}/{total}",
            "hint": "",
        })
    slides.append({
        "kind": "closing", "big": record.get("supporting_copy") or "", "small": "",
        "number": "", "counter": f"{total}/{total}",
        "hint": "Save this \u00b7 Send it to someone who needs it",
    })
    return slides


def build_carousel_html(record, brand, artwork, slide):
    template = brand.template if brand is not None else BrandTemplate()
    try:
        source = CAROUSEL_TEMPLATE.read_text(encoding="utf-8")
    except OSError as error:
        raise MediaRenderError(f"Could not read {CAROUSEL_TEMPLATE}: {error}") from error
    return Template(source).substitute(
        background=template.background,
        background_rgba_strong=_rgba(template.background, 0.7),
        background_rgba_soft=_rgba(template.background, 0.4),
        text=_NIGHT_COLORS["text"],
        accent=_NIGHT_COLORS["accent"],
        art=_art_html(artwork),
        kind=slide["kind"],
        tone=text_tone(artwork, record) if slide["kind"] == "cover" else "dark",
        big=_copy_html(slide["big"]),
        small=_copy_html(slide["small"]),
        number=escape(slide["number"]),
        counter=escape(slide["counter"]),
        hint=escape(slide["hint"]),
        handle=escape(template.handle or ""),
        placement=(
            placement_script(artwork, record, INSTAGRAM_FEED_SIZE)
            if slide["kind"] == "cover"
            else ""
        ),
    )


def render_carousel(post_id, record, brand, artwork):
    """Render every slide to a 1080x1350 JPEG; return their paths in order."""
    for field in ("title", "main_point", "slides", "supporting_copy"):
        if not str(record.get(field) or "").strip():
            raise MediaRenderError(f"Cannot render the carousel; missing {field}.")
    slides = carousel_slides(record)
    paths = [
        render_html_to_jpeg(
            build_carousel_html(record, brand, artwork, slide),
            carousel_slide_path(post_id, number),
            INSTAGRAM_FEED_SIZE,
        )
        for number, slide in enumerate(slides, start=1)
    ]
    # Remove slides left over from a longer earlier version.
    for number in range(len(slides) + 1, MAX_CAROUSEL_SLIDES + 1):
        carousel_slide_path(post_id, number).unlink(missing_ok=True)
    return paths


def is_image_reel(record):
    return record.get("format_id") == "image_reel"


def reel_layout(record):
    layout = record.get("layout") or "panel"
    return layout if layout in IMAGE_REEL_LAYOUTS else "panel"


def build_post_html(record, brand=None, artwork=None, layer="full"):
    """Return the finished page for a single-page post or one-image Reel.

    For one-image Reels, ``layer`` selects "background" (art only) or "text"
    (copy on a transparent page) so the video can move them separately.
    """
    missing = [
        field
        for field in _REQUIRED_FIELDS
        if not isinstance(record.get(field), str) or not record[field].strip()
    ]
    if missing:
        raise MediaRenderError(
            "Cannot render a post image; missing content: " + ", ".join(missing)
        )
    template = brand.template if brand is not None else BrandTemplate()
    try:
        style = visual_style_for(record)
    except ArtGenerationError as error:
        raise MediaRenderError(str(error)) from error
    if style and style.get("palette") == "night":
        template = replace(template, **_NIGHT_COLORS)
    labels = [
        label.strip()
        for label in str(record.get("visual_labels") or "").replace("\n", ",").split(",")
        if label.strip() and label.strip().casefold() != "none"
    ]
    labels_html = (
        '<div class="labels">'
        + "".join(f"<span>{escape(label)}</span>" for label in labels)
        + "</div>"
        if labels
        else ""
    )
    if is_designed(record):
        layout = "designed"
    elif is_image_reel(record):
        layout = "image_reel"
    elif record.get("layout") == "poster":
        layout = "feed_poster"
    else:
        layout = layout_for(brand)
    if layout in ("quote_painting", "image_reel", "feed_poster", "designed") and artwork is None:
        raise MediaRenderError(
            "This layout paints background artwork first; generate "
            "the artwork, then render the image."
        )
    if layout == "image_reel":
        template_path = (
            IMAGE_REEL_POSTER_TEMPLATE
            if reel_layout(record) == "poster"
            else IMAGE_REEL_TEMPLATE
        )
    elif layout == "feed_poster":
        template_path = FEED_POSTER_TEMPLATE
    elif layout == "designed":
        template_path = DESIGNED_TEMPLATE
    else:
        template_path = _LAYOUT_TEMPLATES[layout]
    try:
        source = template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise MediaRenderError(
            f"Could not read image template {template_path}: {error}"
        ) from error
    return Template(source).substitute(
        background=template.background,
        background_rgba_strong=_rgba(template.background, 0.88),
        background_rgba_soft=_rgba(template.background, 0.55),
        background_rgba_faint=_rgba(template.background, 0.22),
        text=template.text,
        accent=template.accent,
        font_family=template.font_family,
        art=(
            _art_html(artwork)
            if layout in ("quote_painting", "image_reel", "feed_poster", "designed")
            and layer != "text"
            else ""
        ),
        layer=layer,
        look=weather_look(record) or "none",
        placement=(
            placement_script(
                artwork, record, IMAGE_REEL_SIZE if is_image_reel(record) else INSTAGRAM_FEED_SIZE
            )
            if template_path in (IMAGE_REEL_POSTER_TEMPLATE, FEED_POSTER_TEMPLATE)
            else ""
        ),
        tone=(
            text_tone(artwork, record)
            if template_path in (IMAGE_REEL_POSTER_TEMPLATE, FEED_POSTER_TEMPLATE)
            else "dark"
        ),
        title=_copy_html(record["title"]),
        kicker=escape(series_label(record)),
        cta=escape(str(record.get("cta") or "").strip()),
        main_point=_copy_html(record["main_point"]),
        supporting_copy=_copy_html(record["supporting_copy"]),
        labels=labels_html,
        brand_name=escape(brand.display_name) if brand is not None else "",
        handle=escape(template.handle or ""),
        footer=escape(_footer_text(record, template.handle)),
    )


def render_html_to_jpeg(html, output_path, size=INSTAGRAM_FEED_SIZE):
    return _render_html(html, output_path, size, transparent=False)


def render_html_to_png(html, output_path, size):
    """Render a page with a transparent background, e.g. a text overlay."""
    return _render_html(html, output_path, size, transparent=True)


def _render_html(html, output_path, size, transparent):
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise MediaRenderError(
            "Image rendering needs Playwright. Run: "
            "python3 -m pip install playwright && "
            "python3 -m playwright install chromium"
        ) from error
    width, height = size
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height}
                )
                page.set_content(html, wait_until="load")
                overflow = page.evaluate("document.body.dataset.overflow")
                if transparent:
                    page.screenshot(
                        path=str(output_path), type="png", omit_background=True
                    )
                else:
                    page.screenshot(
                        path=str(output_path), type="jpeg", quality=95
                    )
            finally:
                browser.close()
    except PlaywrightError as error:
        raise MediaRenderError(f"Could not render the post image: {error}") from error
    if overflow == "true":
        raise MediaRenderError(
            "The post copy is too long to fit the image; shorten the main "
            "point or supporting copy and render again."
        )
    return output_path


# Where the still image (and the Reel cover) is taken from a motion clip.
VIDEO_STILL_SECONDS = 2


def ffmpeg_executable():
    try:
        import imageio_ffmpeg
    except ImportError as error:
        raise MediaRenderError(
            "Video rendering needs ffmpeg. Run: python3 -m pip install imageio-ffmpeg"
        ) from error
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_video_frame(video, output, seconds=VIDEO_STILL_SECONDS):
    """Save one frame of a clip as a PNG (falls back to the first frame)."""
    for at in (seconds, 0):
        result = subprocess.run(
            [ffmpeg_executable(), "-y", "-loglevel", "error", "-ss", str(at),
             "-i", str(video), "-frames:v", "1", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and output.is_file() and output.stat().st_size:
            return output
    raise MediaRenderError(f"Could not read a frame from {video.name}.")


def render_post_image(post_id):
    """Render a saved post to a JPEG: 1080x1350, or 1080x1920 for image Reels."""
    record = load_post(post_id)
    if record.get("format_id", "single_page") not in _RENDERABLE_FORMATS:
        raise MediaRenderError(
            "Only single-page posts and one-image Reels can be rendered."
        )
    brand = _brand_for(record)
    artwork = (
        artwork_path(post_id)
        if is_image_reel(record)
        or is_carousel(record)
        or is_designed(record)
        or record.get("layout") == "poster"
        or layout_for(brand) == "quote_painting"
        else None
    )
    if is_carousel(record):
        if artwork is None:
            raise MediaRenderError("Add the cover artwork first; the slides reuse it.")
        with tempfile.TemporaryDirectory() as folder:
            if is_video_artwork(artwork):
                artwork = extract_video_frame(artwork, Path(folder) / "frame.png")
            paths = render_carousel(post_id, record, brand, artwork)
        record["slide_count"] = len(paths)
        try:
            record["image_path"] = str(paths[0].relative_to(PROJECT_ROOT))
        except ValueError:
            record["image_path"] = str(paths[0])
        save_post(post_id, record)
        return paths[0]
    with tempfile.TemporaryDirectory() as folder:
        if is_video_artwork(artwork):
            artwork = extract_video_frame(artwork, Path(folder) / "frame.png")
        html = build_post_html(record, brand, artwork)
        output_path = render_html_to_jpeg(
            html,
            post_image_path(post_id),
            IMAGE_REEL_SIZE if is_image_reel(record) else INSTAGRAM_FEED_SIZE,
        )
    try:
        record["image_path"] = str(output_path.relative_to(PROJECT_ROOT))
    except ValueError:
        record["image_path"] = str(output_path)
    save_post(post_id, record)
    return output_path
