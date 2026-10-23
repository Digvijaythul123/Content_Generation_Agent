from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple
import re


_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
_REEL_FIELDS = ("title", "hook", "script", "caption")


class ContentValidationError(ValueError):
    """Raised when configuration or generated content violates its contract."""


def _required_string(data, key, context):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentValidationError(
            f"{context} requires a non-empty {key!r} string."
        )
    return value.strip()


def _string_list(data, key, context):
    value = data.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContentValidationError(
            f"{context} requires {key!r} to be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _validate_id(identifier, context):
    if not isinstance(identifier, str) or not _ID_PATTERN.fullmatch(identifier):
        raise ContentValidationError(
            f"{context} ID must contain only lowercase letters, numbers, "
            "and underscores."
        )
    return identifier


def validate_identifier(identifier, context):
    try:
        return _validate_id(identifier, context)
    except ContentValidationError as error:
        if context == "Content profile":
            raise ContentValidationError(
                f"Invalid profile ID {identifier!r}; use lowercase letters, "
                "numbers, and underscores."
            ) from error
        raise


@dataclass(frozen=True)
class VisualGuidance:
    image_style: Tuple[str, ...] = ()
    setting: Tuple[str, ...] = ()
    image_requirements: Tuple[str, ...] = ()
    camera: Tuple[str, ...] = ()
    music: Tuple[str, ...] = ()
    subtitles: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data, profile_id):
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"Content profile {profile_id!r} 'visual' must be a mapping."
            )
        return cls(
            image_style=_optional_string_list(data, "image_style", profile_id),
            setting=_optional_string_list(data, "setting", profile_id),
            image_requirements=_optional_string_list(
                data, "image_requirements", profile_id
            ),
            camera=_optional_string_list(data, "camera", profile_id),
            music=_optional_string_list(data, "music", profile_id),
            subtitles=_optional_string_list(data, "subtitles", profile_id),
        )

    def to_mapping(self):
        return {
            "image_style": list(self.image_style),
            "setting": list(self.setting),
            "image_requirements": list(self.image_requirements),
            "camera": list(self.camera),
            "music": list(self.music),
            "subtitles": list(self.subtitles),
        }


@dataclass(frozen=True)
class ContentProfile:
    id: str
    display_name: str
    language: str
    audience_description: str
    objectives: Tuple[str, ...]
    voice_traits: Tuple[str, ...]
    voice_avoid: Tuple[str, ...]
    topics: Tuple[str, ...]
    visual: VisualGuidance = VisualGuidance()

    @classmethod
    def from_mapping(cls, data):
        context = "Content profile"
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"{context} configuration must be a YAML mapping."
            )
        identifier = _validate_id(_required_string(data, "id", context), context)
        audience = data.get("audience")
        voice = data.get("voice")
        visual = data.get("visual", {})
        if not isinstance(audience, Mapping):
            raise ContentValidationError(
                f"{context} {identifier!r} requires an 'audience' mapping."
            )
        if not isinstance(voice, Mapping):
            raise ContentValidationError(
                f"{context} {identifier!r} requires a 'voice' mapping."
            )
        return cls(
            id=identifier,
            display_name=_required_string(data, "display_name", context),
            language=_required_string(data, "language", context),
            audience_description=_required_string(
                audience, "description", f"{context} {identifier!r} audience"
            ),
            objectives=_string_list(data, "objectives", f"{context} {identifier!r}"),
            voice_traits=_string_list(voice, "traits", f"{context} {identifier!r} voice"),
            voice_avoid=_string_list(voice, "avoid", f"{context} {identifier!r} voice"),
            topics=_string_list(data, "topics", f"{context} {identifier!r}"),
            visual=VisualGuidance.from_mapping(visual, identifier),
        )

    def to_mapping(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "language": self.language,
            "audience": {"description": self.audience_description},
            "objectives": list(self.objectives),
            "voice": {
                "traits": list(self.voice_traits),
                "avoid": list(self.voice_avoid),
            },
            "topics": list(self.topics),
            "visual": self.visual.to_mapping(),
        }


@dataclass(frozen=True)
class BrandTemplate:
    """Colours and type used when rendering finished post images."""

    background: str = "#F4EFE6"
    text: str = "#1D1B19"
    accent: str = "#B5532E"
    font_family: str = "Georgia, 'Times New Roman', serif"
    handle: Optional[str] = None
    layout: str = "classic"
    art_style: Optional[str] = None

    @classmethod
    def from_mapping(cls, data, brand_id):
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"Brand {brand_id!r} 'template' must be a mapping."
            )
        values = {}
        for key in ("background", "text", "accent"):
            if key in data:
                value = data[key]
                if not isinstance(value, str) or not _HEX_COLOR_PATTERN.fullmatch(
                    value
                ):
                    raise ContentValidationError(
                        f"Brand {brand_id!r} template.{key} must be a hex "
                        "colour such as '#1D1B19'."
                    )
                values[key] = value
        for key in ("font_family", "handle"):
            if key in data:
                value = data[key]
                if not isinstance(value, str) or not value.strip() or any(
                    character in value for character in "<>{};"
                ):
                    raise ContentValidationError(
                        f"Brand {brand_id!r} template.{key} must be plain text."
                    )
                values[key] = value.strip()
        if "layout" in data:
            if data["layout"] not in BRAND_TEMPLATE_LAYOUTS:
                raise ContentValidationError(
                    f"Brand {brand_id!r} template.layout must be one of: "
                    + ", ".join(BRAND_TEMPLATE_LAYOUTS)
                )
            values["layout"] = data["layout"]
        if "art_style" in data:
            if not isinstance(data["art_style"], str) or not data["art_style"].strip():
                raise ContentValidationError(
                    f"Brand {brand_id!r} template.art_style must be text."
                )
            values["art_style"] = " ".join(data["art_style"].split())
        return cls(**values)


_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
# classic: typographic card. quote_painting: copy over AI background artwork.
BRAND_TEMPLATE_LAYOUTS = ("classic", "quote_painting")


@dataclass(frozen=True)
class Brand:
    id: str
    display_name: str
    default_profile_id: str
    default_format_id: str
    default_platform_id: str
    voice_traits: Tuple[str, ...] = ()
    voice_avoid: Tuple[str, ...] = ()
    template: BrandTemplate = BrandTemplate()

    @classmethod
    def from_mapping(cls, data):
        context = "Brand"
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"{context} configuration must be a YAML mapping."
            )
        identifier = _validate_id(_required_string(data, "id", context), context)
        voice = data.get("voice", {})
        if not isinstance(voice, Mapping):
            raise ContentValidationError(
                f"Brand {identifier!r} 'voice' must be a mapping."
            )
        return cls(
            id=identifier,
            display_name=_required_string(data, "display_name", context),
            default_profile_id=_validate_id(
                _required_string(data, "default_profile_id", context),
                "Default profile",
            ),
            default_format_id=_validate_id(
                _required_string(data, "default_format_id", context),
                "Default format",
            ),
            default_platform_id=_validate_id(
                _required_string(data, "default_platform_id", context),
                "Default platform",
            ),
            voice_traits=_optional_string_list(voice, "traits", identifier),
            voice_avoid=_optional_string_list(voice, "avoid", identifier),
            template=BrandTemplate.from_mapping(
                data.get("template", {}), identifier
            ),
        )


@dataclass(frozen=True)
class ContentFormat:
    id: str
    display_name: str
    content_fields: Tuple[str, ...]
    instructions: Tuple[str, ...]
    content_kind: str = "reel"
    prompt_template: Optional[str] = None
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    duration_min_seconds: Optional[int] = None
    duration_max_seconds: Optional[int] = None

    @classmethod
    def from_mapping(cls, data):
        context = "Content format"
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"{context} configuration must be a YAML mapping."
            )
        identifier = _validate_id(_required_string(data, "id", context), context)
        content_fields = _string_list(
            data, "content_fields", f"{context} {identifier!r}"
        )
        if not content_fields or len(set(content_fields)) != len(content_fields):
            raise ContentValidationError(
                f"Content format {identifier!r} must define unique content fields."
            )
        generation = data.get("generation", {})
        media = data.get("media", {})
        if not isinstance(generation, Mapping) or not isinstance(media, Mapping):
            raise ContentValidationError(
                f"Content format {identifier!r} 'generation' and 'media' "
                "values must be mappings."
            )
        content_kind = generation.get("content_kind", "reel")
        if content_kind not in ("reel", "post"):
            raise ContentValidationError(
                f"Content format {identifier!r} content_kind must be "
                "'reel' or 'post'."
            )
        prompt_template = generation.get("prompt_template")
        if prompt_template is not None and (
            not isinstance(prompt_template, str)
            or not re.fullmatch(r"[a-z0-9_]+\.md", prompt_template)
        ):
            raise ContentValidationError(
                f"Content format {identifier!r} prompt_template must be a "
                "Markdown filename."
            )
        duration = media.get("duration_seconds", {})
        if not isinstance(duration, Mapping):
            raise ContentValidationError(
                f"Content format {identifier!r} duration_seconds must be a mapping."
            )
        minimum = duration.get("minimum")
        maximum = duration.get("maximum")
        for label, value in (("minimum", minimum), ("maximum", maximum)):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ContentValidationError(
                    f"Content format {identifier!r} duration {label} must "
                    "be a positive integer."
                )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ContentValidationError(
                f"Content format {identifier!r} minimum duration exceeds maximum."
            )
        aspect_ratio = media.get("aspect_ratio")
        if aspect_ratio is not None and (
            not isinstance(aspect_ratio, str) or not aspect_ratio.strip()
        ):
            raise ContentValidationError(
                f"Content format {identifier!r} aspect_ratio must be a string."
            )
        resolution = media.get("resolution")
        if resolution is not None and (
            not isinstance(resolution, str) or not resolution.strip()
        ):
            raise ContentValidationError(
                f"Content format {identifier!r} resolution must be a string."
            )
        return cls(
            id=identifier,
            display_name=_required_string(data, "display_name", context),
            content_fields=content_fields,
            instructions=_string_list(
                generation, "instructions", f"{context} {identifier!r} generation"
            )
            if "instructions" in generation
            else (),
            content_kind=content_kind,
            prompt_template=prompt_template,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration_min_seconds=minimum,
            duration_max_seconds=maximum,
        )


# Retain the existing ContentFormat name while exposing the domain name Format.
Format = ContentFormat


@dataclass(frozen=True)
class Platform:
    id: str
    display_name: str
    supported_format_ids: Tuple[str, ...]
    aspect_ratio: Optional[str] = None
    max_video_duration_seconds: Optional[int] = None

    @classmethod
    def from_mapping(cls, data):
        context = "Platform"
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                f"{context} configuration must be a YAML mapping."
            )
        identifier = _validate_id(_required_string(data, "id", context), context)
        constraints = data.get("constraints", {})
        if not isinstance(constraints, Mapping):
            raise ContentValidationError(
                f"Platform {identifier!r} 'constraints' must be a mapping."
            )
        formats = data.get("supported_format_ids", [])
        if not isinstance(formats, list) or not all(
            isinstance(item, str) and _ID_PATTERN.fullmatch(item)
            for item in formats
        ):
            raise ContentValidationError(
                f"Platform {identifier!r} supported_format_ids must be "
                "a list of valid IDs."
            )
        aspect_ratio = constraints.get("aspect_ratio")
        if aspect_ratio is not None and (
            not isinstance(aspect_ratio, str) or not aspect_ratio.strip()
        ):
            raise ContentValidationError(
                f"Platform {identifier!r} aspect_ratio must be a string."
            )
        max_duration = constraints.get("max_video_duration_seconds")
        if max_duration is not None and (
            not isinstance(max_duration, int)
            or isinstance(max_duration, bool)
            or max_duration <= 0
        ):
            raise ContentValidationError(
                f"Platform {identifier!r} max_video_duration_seconds must "
                "be a positive integer."
            )
        return cls(
            id=identifier,
            display_name=_required_string(data, "display_name", context),
            supported_format_ids=tuple(formats),
            aspect_ratio=aspect_ratio,
            max_video_duration_seconds=max_duration,
        )


@dataclass(frozen=True)
class GenerationRequest:
    brand: Optional[Brand]
    profile: ContentProfile
    content_format: ContentFormat
    platform: Platform
    brief: Optional[str] = None
    brand_identity_explicit: bool = False
    category_id: Optional[str] = None
    comedy_subtype: Optional[str] = None
    subtype: Optional[str] = None
    thinker_id: Optional[str] = None
    visual_style: Optional[str] = None
    scenery: Optional[str] = None
    weather: Optional[str] = None


    @property
    def qa_subtype(self):
        """Legacy name: the subtype was first used for QA topic pillars."""
        return self.subtype

@dataclass(frozen=True)
class GeneratedContent:
    fields: Mapping[str, str]
    raw_content: str
    profile_id: Optional[str] = None

    @classmethod
    def from_text(cls, raw_content, required_fields=_REEL_FIELDS):
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise ContentValidationError(
                "The model returned empty or non-text content."
            )
        values = {}
        for index, field in enumerate(required_fields):
            if not isinstance(field, str) or not field.strip():
                raise ContentValidationError(
                    f"Invalid generated content field {field!r}."
                )
            next_field = (
                required_fields[index + 1]
                if index + 1 < len(required_fields)
                else None
            )
            if next_field:
                pattern = rf"^{re.escape(field)}:\s*(.*?)(?=^{re.escape(next_field)}:|\Z)"
                match = re.search(
                    pattern,
                    raw_content,
                    re.IGNORECASE | re.DOTALL | re.MULTILINE,
                )
            else:
                match = re.search(
                    rf"^{re.escape(field)}:\s*(.*)$",
                    raw_content,
                    re.IGNORECASE | re.DOTALL | re.MULTILINE,
                )
            value = match.group(1).strip() if match else ""
            if not value:
                raise ContentValidationError(
                    f"The model response is missing the required "
                    f"{field!r} section."
                )
            values[field] = value
        return cls(fields=values, raw_content=raw_content)

    @classmethod
    def from_legacy_mapping(cls, data):
        if not isinstance(data, Mapping):
            raise ContentValidationError(
                "Legacy reel content must be a JSON object."
            )

        values = {}
        for field in _REEL_FIELDS:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ContentValidationError(
                    f"Legacy reel content requires a non-empty {field!r} string."
                )
            values[field] = value

        raw_content = data.get("raw_content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            raw_content = "\n\n".join(
                f"{field.title()}: {values[field]}" for field in _REEL_FIELDS
            )

        profile_id = data.get("profile_id")
        if profile_id is not None and (
            not isinstance(profile_id, str) or not profile_id.strip()
        ):
            raise ContentValidationError(
                "Legacy reel profile_id must be a non-empty string when present."
            )

        return cls(
            fields=values,
            raw_content=raw_content,
            profile_id=profile_id,
        )

    @property
    def title(self):
        return self.fields.get("title", "")

    @property
    def hook(self):
        return self.fields.get("hook", "")

    @property
    def script(self):
        return self.fields.get("script", "")

    @property
    def caption(self):
        return self.fields.get("caption", "")

    def to_legacy_mapping(self):
        mapping = {**self.fields, "raw_content": self.raw_content}
        if self.profile_id is not None:
            mapping["profile_id"] = self.profile_id
        return mapping


def _optional_string_list(data: Mapping[str, Any], key: str, brand_id: str):
    value = data.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContentValidationError(
            f"Brand {brand_id!r} voice.{key} must be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


INSTAGRAM_CAPTION_MAX_CHARACTERS = 2200
# Threads rejects longer posts, so captions shared there must stay within it.
THREADS_MAX_CHARACTERS = 500
# Instagram now caps posts at 5 hashtags; a few precise tags work best.
INSTAGRAM_MAX_HASHTAGS = 5
_HASHTAG_PATTERN = re.compile(r"(?<!\w)#\w+")


def tidy_caption(caption):
    """Put the source line and the hashtag block on their own lines."""
    text = re.sub(r"[ \t]*(?<!\n)\b(Teaching:|Source:)", r"\n\n\1", caption.strip())
    # Close the source line at its first sentence end inside the paragraph.
    text = re.sub(
        r"^((?:Teaching|Source):[^\n]*?\))\.?[ \t]+(?=\S)",
        r"\1\n\n",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"[ \t]+((?:#\w+\s*){2,})$", r"\n\n\1", text)
    # Gather the closing hashtags onto one line, even if split across lines.
    text = re.sub(
        r"(?:#\w+\s*)+$", lambda match: " ".join(match.group(0).split()), text
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_ANSWER_PATTERN = re.compile(r"^\s*(?:Answer|First comment)\s*:\s*(.+?)\s*$", re.I | re.M)


_SOURCE_LINE_PATTERN = re.compile(r"^\s*(?:Teaching|Source|Idea)\s*:.*$", re.I | re.M)


def split_first_comment(caption, hide_source=False):
    """Move an "Answer:" line out of the caption (it goes in the first comment).

    With ``hide_source`` (quiz posts), the Teaching/Source line moves too,
    since it would give the answer away. Returns (caption, first_comment).
    """
    match = _ANSWER_PATTERN.search(caption or "")
    if not match:
        return caption, None
    answer = match.group(1).strip()
    cleaned = caption[: match.start()] + caption[match.end():]
    if hide_source:
        source = _SOURCE_LINE_PATTERN.search(cleaned)
        if source:
            cleaned = cleaned[: source.start()] + cleaned[source.end():]
            answer = f"{answer}\n\n{source.group(0).strip()}"
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned.strip())
    return cleaned, answer


def trim_hashtags(caption, limit=None):
    """Drop hashtags beyond the limit, keeping the first ones in order."""
    limit = INSTAGRAM_MAX_HASHTAGS if limit is None else limit
    seen = 0

    def keep(match):
        nonlocal seen
        seen += 1
        return match.group(0) if seen <= limit else ""

    trimmed = _HASHTAG_PATTERN.sub(keep, caption)
    return re.sub(r"[ \t]+(\n|$)", r"\1", trimmed).rstrip()


def validate_instagram_caption(caption):
    """Raise when a caption breaks Instagram's publishing limits."""
    if not isinstance(caption, str) or not caption.strip():
        raise ContentValidationError("Instagram posts require a caption.")
    if len(caption) > INSTAGRAM_CAPTION_MAX_CHARACTERS:
        raise ContentValidationError(
            f"Instagram captions are limited to "
            f"{INSTAGRAM_CAPTION_MAX_CHARACTERS} characters; this caption "
            f"has {len(caption)}."
        )
    hashtag_count = len(_HASHTAG_PATTERN.findall(caption))
    if hashtag_count > INSTAGRAM_MAX_HASHTAGS:
        raise ContentValidationError(
            f"Instagram captions are limited to {INSTAGRAM_MAX_HASHTAGS} "
            f"hashtags; this caption has {hashtag_count}."
        )
    return caption.strip()
