import yaml

from content_models import (
    Brand,
    ContentFormat,
    ContentProfile,
    ContentValidationError,
    GenerationRequest,
    Platform,
    validate_identifier,
)
from project_paths import CONFIG_DIRECTORY


class ConfigurationError(ValueError):
    """Raised when configuration files are missing, invalid, or incompatible."""


def _load_mapping(path, context):
    if not path.is_file():
        raise ConfigurationError(f"{context} configuration not found: {path}")
    try:
        with path.open(encoding="utf-8") as config_file:
            value = yaml.safe_load(config_file)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(
            f"Could not load {context} configuration at {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"{context} configuration at {path} must be a YAML mapping."
        )
    return value


def _load_model(directory, identifier, model_class, context):
    try:
        validate_identifier(identifier, context)
    except ContentValidationError as error:
        raise ConfigurationError(str(error)) from error
    path = CONFIG_DIRECTORY / directory / f"{identifier}.yaml"
    if not path.is_file():
        if context == "Content profile":
            raise ConfigurationError(
                f"Content profile {identifier!r} was not found at {path}."
            )
        raise ConfigurationError(f"{context} configuration not found: {path}")
    try:
        data = _load_mapping(path, context)
        model = model_class.from_mapping(data)
    except ContentValidationError as error:
        raise ConfigurationError(
            f"Invalid {context.lower()} configuration {identifier!r}: {error}"
        ) from error
    if model.id != identifier:
        raise ConfigurationError(
            f"{context} filename ID {identifier!r} does not match "
            f"configured ID {model.id!r}."
        )
    return model


def load_brand(brand_id):
    return _load_model("brands", brand_id, Brand, "Brand")


def load_profile_config(profile_id):
    return _load_model(
        "content_profiles", profile_id, ContentProfile, "Content profile"
    )


def load_format(format_id):
    return _load_model("formats", format_id, ContentFormat, "Content format")


def load_platform(platform_id):
    return _load_model("platforms", platform_id, Platform, "Platform")


def resolve_generation_request(
    brand_id=None,
    profile_id=None,
    format_id=None,
    platform_id=None,
    brief=None,
):
    brand_was_explicit = brand_id is not None
    brand = load_brand(brand_id or "default")
    profile = load_profile_config(profile_id or brand.default_profile_id)
    content_format = load_format(format_id or brand.default_format_id)
    platform = load_platform(platform_id or brand.default_platform_id)

    if platform.supported_format_ids and (
        content_format.id not in platform.supported_format_ids
    ):
        raise ConfigurationError(
            f"Platform {platform.id!r} does not support format "
            f"{content_format.id!r}."
        )
    if (
        platform.aspect_ratio
        and content_format.aspect_ratio
        and platform.aspect_ratio != content_format.aspect_ratio
    ):
        raise ConfigurationError(
            f"Format {content_format.id!r} aspect ratio "
            f"{content_format.aspect_ratio!r} conflicts with platform "
            f"{platform.id!r} aspect ratio {platform.aspect_ratio!r}."
        )
    if (
        platform.max_video_duration_seconds is not None
        and content_format.duration_max_seconds is not None
        and content_format.duration_max_seconds
        > platform.max_video_duration_seconds
    ):
        raise ConfigurationError(
            f"Format {content_format.id!r} maximum duration exceeds "
            f"platform {platform.id!r} maximum duration."
        )

    return GenerationRequest(
        brand=brand,
        profile=profile,
        content_format=content_format,
        platform=platform,
        brief=brief,
        brand_identity_explicit=brand_was_explicit,
    )
