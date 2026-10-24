from dataclasses import dataclass, replace
from pathlib import Path
import json

from content_models import (
    ContentValidationError,
    GeneratedContent,
    GenerationRequest,
    THREADS_MAX_CHARACTERS,
    tidy_caption,
    trim_hashtags,
    validate_instagram_caption,
)
import random
import re

from config_loader import (
    ConfigurationError,
    load_focus_thinkers,
    load_profile_sceneries,
    load_profile_subtypes,
    load_profile_weathers,
    resolve_generation_request,
)
from content_agent import ContentAgent


@dataclass(frozen=True)
class GenerationResult:
    request: GenerationRequest
    content: GeneratedContent


def generate_content(
    profile_id=None,
    brand_id=None,
    format_id=None,
    platform_id=None,
    brief=None,
    category_id=None,
    comedy_subtype=None,
    subtype=None,
    qa_subtype=None,
    thinker_id=None,
    visual_style=None,
    caption_language="english",
    scenery=None,
    weather=None,
    hashtag_count=None,
):
    """Resolve configuration, generate a draft, and validate its content.

    ``scenery`` and ``weather`` take an id, "auto" or None to rotate, or
    "none" to leave the place or light to the story.
    """
    subtype = subtype or qa_subtype  # legacy keyword
    request = resolve_generation_request(
        brand_id=brand_id,
        profile_id=profile_id,
        format_id=format_id,
        platform_id=platform_id,
        brief=brief,
        category_id=category_id,
        comedy_subtype=comedy_subtype,
        subtype=subtype,
        thinker_id=thinker_id,
        visual_style=visual_style,
    )
    if request.thinker_id is None and not brief and request.category_id != "comedy":
        thinker_id = _pick_thinker(request.profile.id, request.subtype)
    if thinker_id is not None and thinker_id != request.thinker_id:
        # Resolve again so the rotated thinker is validated and saved.
        request = resolve_generation_request(
            brand_id=brand_id,
            profile_id=profile_id,
            format_id=format_id,
            platform_id=platform_id,
            brief=brief,
            category_id=category_id,
            comedy_subtype=comedy_subtype,
            subtype=subtype,
            thinker_id=thinker_id,
            visual_style=visual_style,
        )
    chosen_scenery = _pick_setting(request, "sceneries", scenery)
    # A full moon post needs the moon in the sky.
    if (weather in (None, "auto")) and brief and "full moon" in brief.lower():
        weather = "moonlit_night"
    request = replace(
        request,
        scenery=chosen_scenery,
        weather=_pick_setting(request, "weathers", weather, avoid=_CLASHES.get(chosen_scenery, ())),
    )
    agent = ContentAgent(
        profile_id=request.profile.id,
        profile=request.profile.to_mapping(),
        brand=request.brand,
        content_format=request.content_format,
        platform=request.platform,
        brief=request.brief,
        brand_identity_explicit=request.brand_identity_explicit,
        brand_selected=request.brand is not None,
        category_id=request.category_id,
        comedy_subtype=request.comedy_subtype,
        subtype=request.subtype,
        thinker_id=request.thinker_id,
        visual_style=request.visual_style,
        caption_language=caption_language,
        scenery=request.scenery,
        weather=request.weather,
        hashtag_count=hashtag_count,
    )
    raw_content = agent.generate_content()
    try:
        content = GeneratedContent.from_text(
            raw_content, request.content_format.content_fields
        )
    except ContentValidationError as error:
        raise ContentValidationError(
            f"Generated content does not satisfy format "
            f"{request.content_format.id!r}: {error}"
        ) from error
    main_point = content.fields.get("main_point", "")
    if "\n" in main_point and main_point.count('"') == 2 and main_point[0] == main_point[-1] == '"':
        # A list wrapped in one pair of quote marks: keep just the lines.
        content = GeneratedContent(
            fields={**content.fields, "main_point": main_point[1:-1].strip()},
            raw_content=content.raw_content,
            profile_id=content.profile_id,
        )
    if request.platform.id.startswith("instagram") and "caption" in content.fields:
        trimmed = tidy_caption(trim_hashtags(content.fields["caption"], hashtag_count))
        if trimmed != content.fields["caption"]:
            content = GeneratedContent(
                fields={**content.fields, "caption": trimmed},
                raw_content=content.raw_content,
                profile_id=content.profile_id,
            )
        shorter = _fit_caption_for_threads(agent, content.fields["caption"])
        if shorter != content.fields["caption"]:
            content = GeneratedContent(
                fields={**content.fields, "caption": shorter},
                raw_content=content.raw_content,
                profile_id=content.profile_id,
            )
        validate_instagram_caption(content.fields["caption"])
    return GenerationResult(request=request, content=content)


# How many recent posts to look back on so a place or weather is not repeated.
_SETTING_MEMORY = 8
_POSTS_DIRECTORY = Path(__file__).resolve().parent / "generated_posts"


def _uses_setting(request):
    """Art-based posts get a place; illustrated list pages do not."""
    if "design_prompt" not in request.content_format.content_fields:
        return False
    if not request.subtype or request.content_format.id == "carousel":
        return True
    for item in load_profile_subtypes(request.profile.id):
        if item["id"] == request.subtype:
            return not item.get("designed_image") or item["id"] == "parable_card"
    return True


# Weather that does not belong in a place (rotation skips these pairs).
_CLASHES = {
    "frozen_north": ("monsoon_rain", "after_rain", "golden_hour"),
    "snowy_forest": ("monsoon_rain", "after_rain"),
    "himalayan_peaks": ("monsoon_rain",),
    "desert_dunes": ("snowfall", "monsoon_rain", "after_rain"),
    "tropical_beach": ("snowfall",),
    "savanna": ("snowfall",),
    "rice_terraces": ("snowfall",),
    "lotus_pond": ("snowfall",),
    "forest_waterfall": ("snowfall",),
    "cherry_blossoms": ("snowfall", "storm_clouds"),
    "cave_temple": ("snowfall",),
    "sea_cave": ("snowfall",),
}


def _pick_setting(request, kind, choice, avoid=()):
    loader = load_profile_sceneries if kind == "sceneries" else load_profile_weathers
    field = "scenery" if kind == "sceneries" else "weather"
    options = [item["id"] for item in loader(request.profile.id)]
    if choice == "none" or not options or not _uses_setting(request):
        return None
    if choice and choice != "auto":
        if choice not in options:
            raise ConfigurationError(f"Unknown {field} {choice!r}.")
        return choice
    recent = []
    paths = sorted(_POSTS_DIRECTORY.glob("post_*.json"), key=lambda path: path.stat().st_mtime)
    for path in reversed(paths):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get(field)
        except (OSError, ValueError):
            continue
        if value:
            recent.append(value)
        if len(recent) >= _SETTING_MEMORY:
            break
    allowed = [option for option in options if option not in avoid] or options
    fresh = [option for option in allowed if option not in recent]
    return random.choice(fresh or allowed)


def _pick_thinker(profile_id, story_mode):
    """Rotate thinkers so drafts do not collapse onto one favourite voice.

    Verified-quote drafts only pick thinkers with quotes on file.
    """
    thinkers = load_focus_thinkers(profile_id)
    if story_mode == "verified_quote":
        thinkers = [thinker for thinker in thinkers if thinker.get("quotes")]
    return random.choice(thinkers)["id"] if thinkers else None


def _fit_caption_for_threads(agent, caption):
    """Shorten an over-long caption once, keeping its source and hashtags.

    Instagram allows 2,200 characters but sharing to Threads fails above
    500; the shorter version is used only if nothing essential was lost.
    """
    if len(caption) <= THREADS_MAX_CHARACTERS:
        return caption
    try:
        shorter = agent.shorten_caption(caption, THREADS_MAX_CHARACTERS)
    except Exception:  # A failed retry keeps the original caption.
        return caption
    keep = [
        line for line in caption.splitlines()
        if line.startswith(("Teaching:", "Source:"))
    ]
    tags = re.findall(r"(?<!\w)#\w+", caption)
    if (
        not shorter
        or len(shorter) > THREADS_MAX_CHARACTERS
        or any(line not in shorter for line in keep)
        or any(tag not in shorter for tag in tags)
    ):
        return caption
    return shorter
