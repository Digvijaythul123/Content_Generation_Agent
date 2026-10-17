import sys

from config_loader import (
    ConfigurationError,
    load_comedy_config,
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
)


def _render_timing_cues(storyboard):
    lines = []
    for scene in storyboard.scenes:
        timing = (
            "UNTIMED"
            if scene.start_seconds is None
            else (
                f"{format_timecode(scene.start_seconds)}-"
                f"{format_timecode(scene.end_seconds)}"
            )
        )
        lines.append(f"{scene.id} | {timing}")
        for label, cues in (
            ("SFX", scene.sound_cues),
            ("CAMERA", scene.camera_notes),
            ("CUT", (scene.transition,) if scene.transition else ()),
            ("CONTINUITY", scene.continuity),
        ):
            lines.extend(f"  {label}: {cue}" for cue in cues)
    return "\n".join(lines)


def generate_master_prompt(reel_id):
    validate_reel_id(reel_id)
    reel = load_reel(reel_id)
    profile = load_profile_config(
        reel.get("profile_id", "rational_thoughts")
    )
    comedy = (
        load_comedy_config()
        if reel.get("category_id") == "comedy"
        else None
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
        timing_cues = ""
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
        timing_cues = _render_timing_cues(storyboard)
    if storyboard is None:
        timing_cues = ""
    aspect_ratio = (
        content_format.aspect_ratio
        or platform.aspect_ratio
        or "unspecified"
    )
    duration = []
    comedy_duration = (
        comedy["formats"].get("reel", {}).get("default_duration_seconds")
        if comedy
        else None
    )
    if comedy_duration:
        duration.append(
            "Recommended duration: "
            f"{comedy_duration['minimum']}-"
            f"{comedy_duration['maximum']} seconds"
        )
    elif content_format.duration_min_seconds is not None:
        duration.append(f"Minimum duration: {content_format.duration_min_seconds} seconds")
    if not comedy_duration and content_format.duration_max_seconds is not None:
        duration.append(f"Maximum duration: {content_format.duration_max_seconds} seconds")
    if (
        not comedy_duration
        and platform.max_video_duration_seconds is not None
    ):
        duration.append(
            f"Platform maximum duration: {platform.max_video_duration_seconds} seconds"
        )
    camera = "; ".join(profile.visual.camera) or "purposeful, readable framing"
    music = "; ".join(profile.visual.music) or "subtle instrumental, no vocals"
    subtitles = "; ".join(profile.visual.subtitles) or "readable, timed captions"
    visual_style = "; ".join(
        profile.visual.image_style + profile.visual.setting
        + profile.visual.image_requirements
    ) or "consistent visual style, realistic lighting, no text in visuals"
    comedy_direction = ""
    if comedy:
        selected = next(
            (
                subtype
                for subtype in comedy["subtypes"]
                if subtype["id"] == reel.get("comedy_subtype")
            ),
            None,
        )
        subtype_direction = (
            f"Selected subtype: {selected['name']} — {selected['definition']}"
            if selected
            else "Choose a visual approach that serves the joke."
        )
        comedy_direction = (
            f"Comedy: {subtype_direction}; time reactions and pauses for "
            "the punchline, using the visual medium that best serves the joke."
        )

    prompt_lines = [
        f"Create {content_format.display_name} for {platform.display_name}: "
        f"{aspect_ratio}, {content_format.resolution or 'configured resolution'}"
        f"{'; ' + '; '.join(duration) if duration else ''}.",
        f"Title: {reel.get('title', '')}",
        "Premise (context, not additional voiceover): "
        f"{storyboard.premise if storyboard is not None else reel.get('hook', '').strip()}",
        f"Visual style: {visual_style}",
    ]
    if comedy_direction:
        prompt_lines.append(comedy_direction)
    prompt_lines.extend(
        [
            f"Voiceover/dialogue:\n{voiceover}",
            f"Timing and production cues:\n{timing_cues}"
            if timing_cues
            else "",
            f"Image prompts (authoritative scene visuals):\n{visual_prompts}",
            f"Camera: {camera}",
            f"Music: {music}",
            f"Subtitles: {subtitles}",
            "Keep scene order, continuity, and punchline timing. No added "
            "dialogue or text.",
        ]
    )
    master_prompt = "\n".join(line for line in prompt_lines if line)

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
