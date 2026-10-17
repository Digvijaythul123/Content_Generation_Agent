import base64
from html import escape
import mimetypes
import re
from string import Template

from art_generator import artwork_path
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
_HIGHLIGHT_PATTERN = re.compile(r"\*\*(.+?)\*\*")
INSTAGRAM_FEED_SIZE = (1080, 1350)
_REQUIRED_FIELDS = ("title", "main_point", "supporting_copy")


class MediaRenderError(RuntimeError):
    """Raised when a post image cannot be rendered."""


def post_image_path(post_id):
    return GENERATED_ASSETS_DIRECTORY / f"{post_id}_instagram.jpg"


def layout_for(brand):
    return brand.template.layout if brand is not None else "classic"


def _copy_html(text):
    """Escape copy and render **keyword** markers as highlighted words."""
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


def _brand_for(record):
    brand_id = record.get("brand_id")
    if not brand_id:
        return None
    return load_brand(brand_id)


def build_post_html(record, brand=None, artwork=None):
    """Return the finished 4:5 page for a single-page post record."""
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
    layout = layout_for(brand)
    if layout == "quote_painting" and artwork is None:
        raise MediaRenderError(
            "This brand's layout paints background artwork first; generate "
            "the artwork, then render the image."
        )
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
        text=template.text,
        accent=template.accent,
        font_family=template.font_family,
        art=_art_html(artwork) if layout == "quote_painting" else "",
        title=_copy_html(record["title"]),
        main_point=_copy_html(record["main_point"]),
        supporting_copy=_copy_html(record["supporting_copy"]),
        labels=labels_html,
        brand_name=escape(brand.display_name) if brand is not None else "",
        handle=escape(template.handle or ""),
    )


def render_html_to_jpeg(html, output_path, size=INSTAGRAM_FEED_SIZE):
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


def render_post_image(post_id):
    """Render a saved post to a 1080x1350 JPEG (Instagram's only image type)."""
    record = load_post(post_id)
    if record.get("format_id", "single_page") != "single_page":
        raise MediaRenderError(
            "Only single-page posts can be rendered as Instagram images."
        )
    brand = _brand_for(record)
    artwork = artwork_path(post_id) if layout_for(brand) == "quote_painting" else None
    html = build_post_html(record, brand, artwork)
    output_path = render_html_to_jpeg(html, post_image_path(post_id))
    try:
        record["image_path"] = str(output_path.relative_to(PROJECT_ROOT))
    except ValueError:
        record["image_path"] = str(output_path)
    save_post(post_id, record)
    return output_path
