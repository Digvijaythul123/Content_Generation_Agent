import sys

from ai_service import AIService, AIServiceError
from config_loader import (
    ConfigurationError,
    load_comedy_config,
    load_format,
    load_platform,
    load_profile_config,
)
from project_paths import GENERATED_IMAGES_DIRECTORY, GENERATED_VIDEOS_DIRECTORY
from reel_storage import ReelStorageError, load_reel, validate_reel_id
from scripts.storyboard_generator import (
    StoryboardValidationError,
    generate_storyboard,
    read_storyboard,
    render_storyboard,
)


def _bullets(items):
    return "\n".join(f"- {item}" for item in items)


def generate_image_prompts(reel_id, ai_service=None):
    validate_reel_id(reel_id)
    reel = load_reel(reel_id)
    storyboard_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_storyboard.json"
    scene_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_scenes.txt"
    script = reel.get("script", "")
    hook = reel.get("hook", "")
    if not isinstance(script, str) or not isinstance(hook, str):
        raise StoryboardValidationError(
            "Reel script and hook must be strings to create image prompts."
        )
    if storyboard_file.is_file():
        storyboard = read_storyboard(storyboard_file)
    elif script.strip() or hook.strip():
        generate_storyboard(reel_id)
        storyboard = read_storyboard(storyboard_file)
    elif scene_file.is_file():
        storyboard = None
    else:
        raise FileNotFoundError(
            f"Storyboard or legacy scenes file not found: {scene_file}"
        )
    scene_content = (
        render_storyboard(storyboard)
        if storyboard is not None
        else scene_file.read_text(encoding="utf-8")
    )
    profile = load_profile_config(
        reel.get("profile_id", "rational_thoughts")
    )
    content_format = load_format(reel.get("format_id", "reel"))
    platform = load_platform(reel.get("platform_id", "instagram"))
    visual = profile.visual
    comedy_direction = ""
    if reel.get("category_id") == "comedy":
        comedy = load_comedy_config()
        selected = next(
            (
                subtype
                for subtype in comedy["subtypes"]
                if subtype["id"] == reel.get("comedy_subtype")
            ),
            None,
        )
        comedy_direction = (
            "Comedy: choose a visual approach that makes the joke readable; "
            "keep the setup/reaction/punchline clear. "
            + (
                f"Subtype: {selected['name']} — {selected['definition']}"
                if selected
                else "Choose the most fitting subtype."
            )
        )

    aspect_ratio = (
        content_format.aspect_ratio
        or platform.aspect_ratio
        or "9:16"
    )
    visual_requirements = list(visual.image_style) + list(visual.setting)
    visual_requirements.extend(visual.image_requirements)
    visual_requirements.append(f"Aspect ratio: {aspect_ratio}")
    if content_format.resolution:
        visual_requirements.append(
            f"Resolution: {content_format.resolution}"
        )

    prompt = (
        f"Create one still-image prompt per scene for {profile.display_name}, "
        f"{content_format.display_name} on {platform.display_name} "
        f"({'; '.join(visual_requirements)}).\n"
        f"{comedy_direction}\n"
        "Keep each image prompt to one concise paragraph of at most 60 words. "
        "Return every scene once, preserving its exact ID/time, as "
        "`SCENE S01 | 0:00-0:05: [prompt]`. Keep character, wardrobe, setting, "
        "and style consistent. Show visual beats only: no readable text, "
        "dialogue, narration, or sound cues.\n\n"
        f"{scene_content}"
    )

    result = (ai_service or AIService()).generate_reel(prompt)
    GENERATED_IMAGES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_file = GENERATED_IMAGES_DIRECTORY / f"{reel_id}_image_prompts.txt"
    output_file.write_text(result, encoding="utf-8")
    return output_file


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m scripts.image_prompt_generator <reel_id>")
        return 1

    reel_id = sys.argv[1]
    try:
        output_file = generate_image_prompts(reel_id)
    except FileNotFoundError as error:
        print(error)
        return 1
    except (
        AIServiceError,
        ConfigurationError,
        ReelStorageError,
        StoryboardValidationError,
    ) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Image prompts saved to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
