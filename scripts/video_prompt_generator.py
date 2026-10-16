import sys

from config_loader import (
    ConfigurationError,
    load_format,
    load_platform,
    load_profile_config,
)
from content_text import clean_script
from project_paths import GENERATED_IMAGES_DIRECTORY, GENERATED_VIDEOS_DIRECTORY
from reel_storage import ReelStorageError, load_reel, validate_reel_id
from scripts.storyboard_generator import (
    StoryboardValidationError,
    format_timecode,
    read_storyboard,
    render_storyboard,
)


def _bullet_section(title, items, fallback=()):
    values = items or fallback
    if not values:
        return ""
    return f"{title}:\n" + "\n".join(f"- {value}" for value in values)


def generate_master_prompt(reel_id):
    validate_reel_id(reel_id)
    reel = load_reel(reel_id)
    profile = load_profile_config(
        reel.get("profile_id", "rational_thoughts")
    )
    content_format = load_format(reel.get("format_id", "reel"))
    platform = load_platform(reel.get("platform_id", "instagram"))

    canonical_image_prompt_file = (
        GENERATED_IMAGES_DIRECTORY / f"{reel_id}_image_prompts.txt"
    )
    legacy_image_prompt_file = (
        GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_image_prompts.txt"
    )
    image_prompt_file = (
        canonical_image_prompt_file
        if canonical_image_prompt_file.is_file()
        else legacy_image_prompt_file
    )
    if not image_prompt_file.is_file():
        raise FileNotFoundError(
            f"Image prompt file not found: {canonical_image_prompt_file}"
        )

    visual_prompts = image_prompt_file.read_text(encoding="utf-8")
    storyboard_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_storyboard.json"
    storyboard = (
        read_storyboard(storyboard_file)
        if storyboard_file.is_file()
        else None
    )
    if storyboard is None:
        voiceover = "\n\n".join(
            value for value in (
                reel.get("hook", "").strip(),
                clean_script(reel.get("script", "")),
            )
            if value
        )
        storyboard_text = ""
    else:
        voiceover_lines = []
        for scene in storyboard.scenes:
            if scene.start_seconds is None:
                timing = "UNTIMED"
            else:
                timing = (
                    f"{format_timecode(scene.start_seconds)}-"
                    f"{format_timecode(scene.end_seconds)}"
                )
            for line in scene.narration:
                voiceover_lines.append(f"[{timing}] {line}")
            for line in scene.dialogue:
                voiceover_lines.append(f"[{timing}] DIALOGUE: {line}")
        voiceover = "\n".join(voiceover_lines) or "No voiceover specified."
        storyboard_text = render_storyboard(storyboard)
    aspect_ratio = (
        content_format.aspect_ratio
        or platform.aspect_ratio
        or "unspecified"
    )
    resolution = (
        f"- Resolution: {content_format.resolution}"
        if content_format.resolution
        else ""
    )
    duration = []
    if content_format.duration_min_seconds is not None:
        duration.append(f"Minimum duration: {content_format.duration_min_seconds} seconds")
    if content_format.duration_max_seconds is not None:
        duration.append(f"Maximum duration: {content_format.duration_max_seconds} seconds")
    if platform.max_video_duration_seconds is not None:
        duration.append(
            f"Platform maximum duration: {platform.max_video_duration_seconds} seconds"
        )
    camera = _bullet_section(
        "CAMERA STYLE",
        profile.visual.camera,
        (
            "Slow cinematic camera movement",
            "Documentary-style visuals",
            "Smooth scene transitions",
            "Shallow depth of field",
        ),
    )
    music = _bullet_section(
        "BACKGROUND MUSIC",
        profile.visual.music,
        (
            "Minimal cinematic instrumental music",
            "No vocals",
        ),
    )
    subtitles = _bullet_section(
        "SUBTITLES",
        profile.visual.subtitles,
        (
            "Burned-in captions",
            "High-contrast readable typography",
            "Match voiceover timing",
        ),
    )
    visual_style = _bullet_section(
        "VISUAL STYLE",
        profile.visual.image_style + profile.visual.setting
        + profile.visual.image_requirements,
        (
            "Consistent visual style",
            "Realistic lighting",
            "No text inside visuals",
        ),
    )

    master_prompt = f"""
Create a polished video for the selected content profile.

TITLE:
{reel.get("title", "")}

HOOK / PREMISE (context, not voiceover unless repeated below):
{storyboard.premise if storyboard is not None else reel.get("hook", "").strip()}

FORMAT:
- {content_format.display_name}
- Destination platform: {platform.display_name}
- Aspect ratio: {aspect_ratio}
{resolution}
{_bullet_section("DURATION", duration)}

{visual_style}

VOICEOVER:

{voiceover}

VISUAL STORYBOARD:

{storyboard_text or visual_prompts}

IMAGE GENERATION PROMPTS:

{visual_prompts}

{camera}

{music}

{subtitles}

OUTPUT:
Create a complete video suitable for the selected format and destination.
"""

    GENERATED_VIDEOS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_master_prompt.txt"
    output_file.write_text(master_prompt, encoding="utf-8")
    return output_file


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m scripts.video_prompt_generator <reel_id>")
        return 1

    reel_id = sys.argv[1]
    try:
        output_file = generate_master_prompt(reel_id)
    except FileNotFoundError as error:
        print(error)
        return 1
    except (
        ConfigurationError,
        ReelStorageError,
        StoryboardValidationError,
    ) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Master video prompt saved to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
