from dataclasses import dataclass

from content_models import (
    ContentValidationError,
    GeneratedContent,
    GenerationRequest,
    trim_hashtags,
    validate_instagram_caption,
)
from config_loader import resolve_generation_request
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
    qa_subtype=None,
    thinker_id=None,
    visual_style=None,
    caption_language="english",
):
    """Resolve configuration, generate a draft, and validate its content."""
    request = resolve_generation_request(
        brand_id=brand_id,
        profile_id=profile_id,
        format_id=format_id,
        platform_id=platform_id,
        brief=brief,
        category_id=category_id,
        comedy_subtype=comedy_subtype,
        qa_subtype=qa_subtype,
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
        qa_subtype=request.qa_subtype,
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
    if request.platform.id.startswith("instagram") and "caption" in content.fields:
        trimmed = trim_hashtags(content.fields["caption"])
        if trimmed != content.fields["caption"]:
            content = GeneratedContent(
                fields={**content.fields, "caption": trimmed},
                raw_content=content.raw_content,
                profile_id=content.profile_id,
            )
        validate_instagram_caption(content.fields["caption"])
    return GenerationResult(request=request, content=content)
