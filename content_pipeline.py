from dataclasses import dataclass

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

from config_loader import load_focus_thinkers, resolve_generation_request
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
):
    """Resolve configuration, generate a draft, and validate its content."""
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
        trimmed = tidy_caption(trim_hashtags(content.fields["caption"]))
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
