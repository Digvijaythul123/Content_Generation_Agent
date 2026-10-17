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


def load_profile_subtypes(profile_id):
    try:
        validate_identifier(profile_id, "Content profile")
    except ContentValidationError as error:
        raise ConfigurationError(str(error)) from error
    path = CONFIG_DIRECTORY / "content_profiles" / f"{profile_id}.yaml"
    data = _load_mapping(path, f"Content profile {profile_id!r}")
    subtypes = data.get("subtypes", [])
    if not isinstance(subtypes, list):
        raise ConfigurationError(
            f"Content profile {profile_id!r} 'subtypes' must be a list."
        )
    identifiers = set()
    for subtype in subtypes:
        if not isinstance(subtype, dict):
            raise ConfigurationError(
                f"Content profile {profile_id!r} subtypes must be mappings."
            )
        identifier = subtype.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ConfigurationError(
                f"Content profile {profile_id!r} subtype requires a non-empty ID."
            )
        try:
            validate_identifier(identifier, "Content profile subtype")
        except ContentValidationError as error:
            raise ConfigurationError(str(error)) from error
        if identifier in identifiers:
            raise ConfigurationError(
                f"Duplicate subtype ID {identifier!r} in content profile "
                f"{profile_id!r}."
            )
        identifiers.add(identifier)
        for key in ("name", "definition"):
            value = subtype.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError(
                    f"Content profile subtype {identifier!r} requires "
                    f"a non-empty {key!r}."
                )
    return subtypes


def load_format(format_id):
    return _load_model("formats", format_id, ContentFormat, "Content format")


def load_platform(platform_id):
    return _load_model("platforms", platform_id, Platform, "Platform")


def load_comedy_config():
    path = CONFIG_DIRECTORY / "comedy.yaml"
    data = _load_mapping(path, "Comedy category")
    if not isinstance(data.get("enabled", True), bool):
        raise ConfigurationError(
            "Comedy category 'enabled' must be true or false."
        )
    for key in ("id", "display_name", "brand_id", "audience"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(
                f"Comedy category requires a non-empty {key!r} string."
            )
    if data["id"] != "comedy":
        raise ConfigurationError(
            "Comedy category configuration ID must be 'comedy'."
        )
    try:
        validate_identifier(data["brand_id"], "Brand")
        load_brand(data["brand_id"])
    except (ContentValidationError, ConfigurationError) as error:
        raise ConfigurationError(
            f"Comedy category has an invalid brand_id: {error}"
        ) from error
    for key in (
        "tone",
        "topics",
        "avoid",
        "humor_guidelines",
        "production_guidelines",
        "visual_approaches",
        "quality_checks",
    ):
        values = data.get(key)
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ConfigurationError(
                f"Comedy category requires {key!r} to be a non-empty "
                "list of strings."
            )
    subtypes = data.get("subtypes")
    if not isinstance(subtypes, list) or len(subtypes) != 10:
        raise ConfigurationError(
            "Comedy category must define exactly ten subtypes."
        )
    identifiers = []
    for subtype in subtypes:
        if not isinstance(subtype, dict):
            raise ConfigurationError(
                "Each Comedy subtype must be a YAML mapping."
            )
        identifier = subtype.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ConfigurationError(
                "Each Comedy subtype requires a non-empty ID."
            )
        try:
            validate_identifier(identifier, "Comedy subtype")
        except ContentValidationError as error:
            raise ConfigurationError(str(error)) from error
        if identifier in identifiers:
            raise ConfigurationError(
                f"Duplicate Comedy subtype ID {identifier!r}."
            )
        identifiers.append(identifier)
        for key in ("name", "definition", "example"):
            value = subtype.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError(
                    f"Comedy subtype {identifier!r} requires {key!r}."
                )
    formats = data.get("formats")
    if not isinstance(formats, dict):
        raise ConfigurationError("Comedy category 'formats' must be a mapping.")
    for format_id in ("reel", "single_page", "linkedin_text_post"):
        format_config = formats.get(format_id)
        requirements = (
            format_config.get("requirements")
            if isinstance(format_config, dict)
            else None
        )
        if not isinstance(requirements, list) or not requirements or not all(
            isinstance(value, str) and value.strip()
            for value in requirements
        ):
            raise ConfigurationError(
                f"Comedy category format {format_id!r} requires a non-empty "
                "requirements list."
            )
    reel_duration = formats["reel"].get("default_duration_seconds")
    if not isinstance(reel_duration, dict) or any(
        not isinstance(reel_duration.get(key), int)
        or isinstance(reel_duration.get(key), bool)
        or reel_duration[key] <= 0
        for key in ("minimum", "maximum")
    ):
        raise ConfigurationError(
            "Comedy Reel format requires positive minimum and maximum "
            "default duration values."
        )
    if reel_duration["minimum"] > reel_duration["maximum"]:
        raise ConfigurationError(
            "Comedy Reel minimum duration exceeds its maximum."
        )
    return data


def resolve_generation_request(
    brand_id=None,
    profile_id=None,
    format_id=None,
    platform_id=None,
    brief=None,
    category_id=None,
    comedy_subtype=None,
    qa_subtype=None,
):
    if category_id is not None and not isinstance(category_id, str):
        raise ConfigurationError("Content category ID must be text.")
    if comedy_subtype is not None and not isinstance(comedy_subtype, str):
        raise ConfigurationError("Comedy subtype ID must be text.")
    if qa_subtype is not None and not isinstance(qa_subtype, str):
        raise ConfigurationError("QA subtype ID must be text.")
    if category_id == "":
        category_id = None
    if comedy_subtype == "":
        comedy_subtype = None
    if qa_subtype == "":
        qa_subtype = None
    if comedy_subtype and not category_id:
        category_id = "comedy"
    if category_id not in (None, "comedy"):
        raise ConfigurationError(
            f"Unknown content category {category_id!r}."
        )
    comedy_config = load_comedy_config() if category_id == "comedy" else None
    if comedy_config and not comedy_config.get("enabled", True):
        raise ConfigurationError("Comedy category is currently disabled.")
    if comedy_subtype:
        subtype_ids = {
            subtype["id"] for subtype in comedy_config["subtypes"]
        }
        if comedy_subtype not in subtype_ids:
            raise ConfigurationError(
                f"Unknown Comedy subtype {comedy_subtype!r}."
            )

    no_brand_selected = brand_id == ""
    brand_was_explicit = bool(brand_id)
    defaults = load_brand("default") if no_brand_selected else None
    selected_brand_id = brand_id
    if (
        brand_id is None
        and category_id == "comedy"
        and format_id != "linkedin_text_post"
    ):
        selected_brand_id = "life_is_a_glitch"
    brand = (
        None
        if no_brand_selected
        else load_brand(selected_brand_id or "default")
    )
    default_context = defaults or brand
    profile = load_profile_config(
        profile_id
        or (
            "comedy"
            if category_id == "comedy" and format_id != "linkedin_text_post"
            else default_context.default_profile_id
        )
    )
    if qa_subtype:
        if profile.id != "qa_engineering_ai":
            raise ConfigurationError(
                "QA subtypes are only available for the QA Engineering & AI profile."
            )
        subtype_ids = {
            subtype["id"] for subtype in load_profile_subtypes(profile.id)
        }
        if qa_subtype not in subtype_ids:
            raise ConfigurationError(f"Unknown QA subtype {qa_subtype!r}.")
    content_format = load_format(
        format_id or default_context.default_format_id
    )
    platform = load_platform(
        platform_id or default_context.default_platform_id
    )
    if category_id == "comedy" and content_format.id not in comedy_config["formats"]:
        raise ConfigurationError(
            f"Comedy category is not configured for format "
            f"{content_format.id!r}."
        )

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
        category_id=category_id,
        comedy_subtype=comedy_subtype,
        qa_subtype=qa_subtype,
    )
