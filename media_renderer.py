import base64
from html import escape
import mimetypes
import re
from string import Template

from dataclasses import replace

import subprocess
import tempfile
from pathlib import Path

from art_generator import (
    ArtGenerationError,
    artwork_path,
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
# "poster" puts the words over open sky in the top third; "panel" uses a
# dark band at the bottom. Records without a layout keep the panel look.
IMAGE_REEL_LAYOUTS = ("poster", "panel")
IMAGE_REEL_SIZE = (1080, 1920)
_RENDERABLE_FORMATS = ("single_page", "image_reel")
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
    source = source_line(record)
    # Quote posts already show the source in their attribution line.
    if source and source.lower() in str(record.get("supporting_copy") or "").lower():
        source = ""
    return " · ".join(part for part in (source, handle) if part)


def _brand_for(record):
    brand_id = record.get("brand_id")
    if not brand_id:
        return None
    return load_brand(brand_id)


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
    layout = "image_reel" if is_image_reel(record) else layout_for(brand)
    if layout in ("quote_painting", "image_reel") and artwork is None:
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
            if layout in ("quote_painting", "image_reel") and layer != "text"
            else ""
        ),
        layer=layer,
        title=_copy_html(record["title"]),
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
        if is_image_reel(record) or layout_for(brand) == "quote_painting"
        else None
    )
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
