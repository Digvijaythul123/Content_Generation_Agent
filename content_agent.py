from ai_service import AIService
import json
from string import Template
import warnings

from profile_loader import load_profile
from project_paths import (
    GENERATED_POSTS_DIRECTORY,
    GENERATED_REELS_DIRECTORY,
    PROMPT_DIRECTORY,
)


PROMPT_TEMPLATE_PATH = PROMPT_DIRECTORY / "content_generation.md"


class ContentAgent:

    def __init__(
        self,
        profile_id="rational_thoughts",
        profile=None,
        brand=None,
        content_format=None,
        platform=None,
        brief=None,
        brand_identity_explicit=False,
    ):
        self.ai_service = AIService()
        self.profile = profile or load_profile(profile_id)
        self.brand = brand
        self.content_format = content_format
        self.platform = platform
        self.brief = brief
        self.brand_identity_explicit = brand_identity_explicit

    def get_previous_titles(self, profile_id=None, brand_id=None):

        titles = []
        selected_profile_id = profile_id or self.profile["id"]
        selected_brand_id = brand_id or getattr(self.brand, "id", "default")
        content_files = []
        for folder in (
            GENERATED_REELS_DIRECTORY,
            GENERATED_POSTS_DIRECTORY,
        ):
            if folder.exists():
                content_files.extend(folder.glob("*.json"))

        for file_path in sorted(content_files):
            try:
                with file_path.open(encoding="utf-8") as reel_file:
                    reel = json.load(reel_file)
            except (OSError, json.JSONDecodeError) as error:
                warnings.warn(
                    f"Skipping unreadable content record {file_path}: {error}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

            if not isinstance(reel, dict):
                warnings.warn(
                    f"Skipping invalid content record {file_path}: expected a "
                    "JSON object.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

            record_profile_id = reel.get("profile_id", "rational_thoughts")
            record_brand_id = reel.get("brand_id", "default")
            title = reel.get("title")
            if (
                record_profile_id == selected_profile_id
                and record_brand_id == selected_brand_id
                and title
            ):
                titles.append(title)

        return titles

    def generate_content(self):

        previous_titles = self.get_previous_titles()
        profile = self.profile

        prompt_template_path = PROMPT_TEMPLATE_PATH
        format_template = getattr(self.content_format, "prompt_template", None)
        if format_template:
            prompt_template_path = PROMPT_DIRECTORY / "formats" / format_template
        with prompt_template_path.open(encoding="utf-8") as prompt_file:
            prompt_template = Template(prompt_file.read())

        prompt = prompt_template.substitute(
            display_name=profile["display_name"],
            audience=profile["audience"]["description"],
            language=profile["language"],
            objectives=_as_bullets(profile["objectives"]),
            voice_traits=", ".join(profile["voice"]["traits"]),
            voice_avoid=", ".join(profile["voice"]["avoid"]),
            topics=_as_bullets(profile["topics"]),
            previous_titles=_as_bullets(previous_titles)
            if previous_titles
            else "- None",
        )

        brand_traits = getattr(self.brand, "voice_traits", ())
        brand_avoid = getattr(self.brand, "voice_avoid", ())
        brand_name = getattr(self.brand, "display_name", None)
        show_brand_identity = (
            self.brand is not None
            and (
                getattr(self, "brand_identity_explicit", False)
                or profile["id"] == getattr(self.brand, "default_profile_id", None)
            )
        )
        brand_context = []
        if show_brand_identity and brand_name and brand_name != profile["display_name"]:
            brand_context.append(f"Publishing brand: {brand_name}")
        if show_brand_identity and brand_traits:
            brand_context.append(
                "Brand voice traits: " + ", ".join(brand_traits)
            )
        if show_brand_identity and brand_avoid:
            brand_context.append("Brand voice to avoid: " + ", ".join(brand_avoid))
        if brand_context:
            prompt = "\n".join(brand_context) + "\n\n" + prompt

        format_instructions = getattr(self.content_format, "instructions", ())
        if format_instructions:
            instructions = "\n".join(
                f"- {instruction}" for instruction in format_instructions
            )
            prompt = (
                f"Selected format requirements:\n{instructions}\n\n" + prompt
            )

        if self.brief:
            prompt = (
                f"Generation brief:\n{self.brief.strip()}\n\n"
                "Follow the profile and format requirements below.\n\n"
                + prompt
            )

        return self.ai_service.generate_reel(prompt)


def _as_bullets(values):
    return "\n".join(f"- {value}" for value in values)