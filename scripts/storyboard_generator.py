import argparse
from dataclasses import dataclass
import json
import re
import sys
from typing import Optional, Tuple

from project_paths import GENERATED_VIDEOS_DIRECTORY
from reel_storage import ReelStorageError, load_reel, validate_reel_id


_TIME_RANGE_PATTERN = re.compile(
    r"\(?(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?)\)?"
)
_TIME_RANGE_PREFIX_PATTERN = re.compile(
    r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?\s*[-–—]"
)
_DIRECTIVE_PATTERN = re.compile(
    r"\b(VOICEOVER|VO|DIALOGUE|VISUAL|SFX|SOUND(?: EFFECT)?|"
    r"TRANSITION|CONTINUITY)\s*:",
    re.IGNORECASE,
)
_CAMERA_NOTE_PATTERN = re.compile(r"\[([^\]]+)\]")
_PARENTHETICAL_VISUAL_PATTERN = re.compile(
    r"\(\s*Visual\s*:\s*(.*?)\)", re.IGNORECASE | re.DOTALL
)
_AUDIBLE_ACTION_PATTERN = re.compile(
    r"(?:^|\s)(We hear\b[^.!?]*[.!?]?)", re.IGNORECASE
)


class StoryboardValidationError(ValueError):
    """Raised when a script cannot be represented by the storyboard contract."""


@dataclass(frozen=True)
class StoryboardScene:
    id: str
    start_seconds: Optional[int]
    end_seconds: Optional[int]
    visual_beats: Tuple[str, ...]
    narration: Tuple[str, ...]
    dialogue: Tuple[str, ...]
    sound_cues: Tuple[str, ...]
    camera_notes: Tuple[str, ...]
    transition: Optional[str]
    continuity: Tuple[str, ...]

    def to_mapping(self):
        return {
            "id": self.id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "visual_beats": list(self.visual_beats),
            "narration": list(self.narration),
            "dialogue": list(self.dialogue),
            "sound_cues": list(self.sound_cues),
            "camera_notes": list(self.camera_notes),
            "transition": self.transition,
            "continuity": list(self.continuity),
        }


@dataclass(frozen=True)
class Storyboard:
    title: str
    premise: str
    duration_seconds: Optional[int]
    scenes: Tuple[StoryboardScene, ...]

    def to_mapping(self):
        return {
            "schema_version": 1,
            "title": self.title,
            "premise": self.premise,
            "duration_seconds": self.duration_seconds,
            "scenes": [scene.to_mapping() for scene in self.scenes],
        }


def _timecode_to_seconds(value):
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        if seconds >= 60:
            raise StoryboardValidationError(
                f"Invalid timecode {value!r}; seconds must be below 60."
            )
        return minutes * 60 + seconds
    hours, minutes, seconds = parts
    if minutes >= 60 or seconds >= 60:
        raise StoryboardValidationError(
            f"Invalid timecode {value!r}; minutes and seconds must be below 60."
        )
    return hours * 3600 + minutes * 60 + seconds


def _clean_value(value):
    return value.strip().strip('"\'“”‘’').strip()


def _parse_scene_content(
    scene_id, text, start_seconds, end_seconds, default_mode="visual"
):
    visual_beats = []
    narration = []
    dialogue = []
    sound_cues = []
    camera_notes = []
    transitions = []
    continuity = []

    restore_directive = (
        "NARRATION" if default_mode == "narration" else "VISUAL"
    )
    text = _PARENTHETICAL_VISUAL_PATTERN.sub(
        lambda match: (
            f"VISUAL: {match.group(1)} {restore_directive}:"
        ),
        text,
    )
    fragments = _DIRECTIVE_PATTERN.split(text)
    mode = default_mode
    for index, fragment in enumerate(fragments):
        if index % 2:
            directive = fragment.upper()
            if directive in ("VO", "VOICEOVER"):
                mode = "narration"
            elif directive == "DIALOGUE":
                mode = "dialogue"
            elif directive == "VISUAL":
                mode = "visual"
            elif directive in ("SFX", "SOUND", "SOUND EFFECT"):
                mode = "sound"
            elif directive == "CONTINUITY":
                mode = "continuity"
            else:
                mode = "transition"
            continue

        value = fragment.strip()
        if not value:
            continue

        for note in _CAMERA_NOTE_PATTERN.findall(value):
            camera_notes.append(_clean_value(note))
        value = _CAMERA_NOTE_PATTERN.sub(" ", value)

        if mode == "visual":
            audible_matches = list(_AUDIBLE_ACTION_PATTERN.finditer(value))
            for match in audible_matches:
                sound_cues.append(_clean_value(match.group(1)))
            value = _AUDIBLE_ACTION_PATTERN.sub(" ", value)

        value = _clean_value(value)
        if not value:
            continue
        if mode == "visual":
            visual_beats.append(value)
        elif mode == "narration":
            narration.append(value)
        elif mode == "dialogue":
            dialogue.append(value)
        elif mode == "sound":
            sound_cues.append(value)
        elif mode == "continuity":
            continuity.append(value)
        else:
            transitions.append(value)

    if len(transitions) > 1:
        raise StoryboardValidationError(
            f"{scene_id} has more than one transition directive."
        )

    return StoryboardScene(
        id=scene_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        visual_beats=tuple(visual_beats),
        narration=tuple(narration),
        dialogue=tuple(dialogue),
        sound_cues=tuple(sound_cues),
        camera_notes=tuple(camera_notes),
        transition=transitions[0] if transitions else None,
        continuity=tuple(continuity),
    )


def build_storyboard(reel):
    script = reel.get("script", "")
    hook = reel.get("hook", "")
    if not isinstance(script, str) or not isinstance(hook, str):
        raise StoryboardValidationError(
            "Reel script and hook must be strings to create a storyboard."
        )

    time_ranges = list(_TIME_RANGE_PATTERN.finditer(script))
    if len(_TIME_RANGE_PREFIX_PATTERN.findall(script)) != len(time_ranges):
        raise StoryboardValidationError(
            "Script contains a malformed time range; expected start-end timecodes."
        )

    scenes = []
    if time_ranges:
        prefix = script[:time_ranges[0].start()].strip()
        previous_end = None
        for index, match in enumerate(time_ranges):
            start_seconds = _timecode_to_seconds(match.group("start"))
            end_seconds = _timecode_to_seconds(match.group("end"))
            if end_seconds <= start_seconds:
                raise StoryboardValidationError(
                    f"Scene {index + 1} must end after it starts."
                )
            if previous_end is not None and start_seconds < previous_end:
                raise StoryboardValidationError(
                    f"Scene {index + 1} overlaps the previous timed scene."
                )
            body_end = (
                time_ranges[index + 1].start()
                if index + 1 < len(time_ranges)
                else len(script)
            )
            body = script[match.end():body_end]
            if index == 0 and prefix:
                body = f"{prefix}\n{body}"
            scene = _parse_scene_content(
                f"S{index + 1:02d}", body, start_seconds, end_seconds
            )
            scenes.append(scene)
            previous_end = end_seconds
        duration_seconds = max(scene.end_seconds for scene in scenes)
    else:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", script)
            if paragraph.strip()
        ]
        if not paragraphs and hook.strip():
            paragraphs = [hook.strip()]
        scenes = [
            _parse_scene_content(
                f"S{index + 1:02d}",
                paragraph,
                None,
                None,
                default_mode="narration",
            )
            for index, paragraph in enumerate(paragraphs)
        ]
        duration_seconds = None

    if not scenes:
        raise StoryboardValidationError(
            "A reel needs a script or hook to create a storyboard."
        )

    return Storyboard(
        title=reel.get("title", "").strip()
        if isinstance(reel.get("title", ""), str)
        else "",
        premise=hook.strip(),
        duration_seconds=duration_seconds,
        scenes=tuple(scenes),
    )


def _format_timecode(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_timecode(seconds):
    return _format_timecode(seconds)


def render_storyboard(storyboard):
    lines = ["STORYBOARD", "=" * 50]
    if storyboard.title:
        lines.extend(["", f"TITLE: {storyboard.title}"])
    if storyboard.premise:
        lines.extend(["", f"PREMISE / HOOK (context, not voiceover): {storyboard.premise}"])
    if storyboard.duration_seconds is not None:
        lines.extend(
            ["", f"TOTAL DURATION: {_format_timecode(storyboard.duration_seconds)}"]
        )

    for scene in storyboard.scenes:
        if scene.start_seconds is None:
            timing = "UNTIMED"
        else:
            timing = (
                f"{_format_timecode(scene.start_seconds)}-"
                f"{_format_timecode(scene.end_seconds)}"
            )
        lines.extend(["", f"SCENE {scene.id} | {timing}"])
        for label, values in (
            ("VISUAL", scene.visual_beats),
            ("NARRATION", scene.narration),
            ("DIALOGUE", scene.dialogue),
            ("SOUND", scene.sound_cues),
            ("CAMERA", scene.camera_notes),
            ("CONTINUITY", scene.continuity),
        ):
            for value in values:
                lines.append(f"{label}: {value}")
        if scene.transition:
            lines.append(f"TRANSITION: {scene.transition}")
    return "\n".join(lines) + "\n"


def read_storyboard(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise StoryboardValidationError(
            f"Invalid storyboard JSON in {path}: {error}"
        ) from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise StoryboardValidationError(
            f"Unsupported storyboard format in {path}."
        )
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise StoryboardValidationError(
            f"Storyboard {path} must contain a non-empty scenes list."
        )
    scenes = []
    required_lists = (
        "visual_beats",
        "narration",
        "dialogue",
        "sound_cues",
        "camera_notes",
        "continuity",
    )
    for index, item in enumerate(raw_scenes, start=1):
        if not isinstance(item, dict):
            raise StoryboardValidationError(
                f"Storyboard {path} contains an invalid scene."
            )
        scene_id = item.get("id")
        start_seconds = item.get("start_seconds")
        end_seconds = item.get("end_seconds")
        if not isinstance(scene_id, str) or not scene_id:
            raise StoryboardValidationError(
                f"Storyboard {path} scene {index} has an invalid ID."
            )
        if (
            (start_seconds is None) != (end_seconds is None)
            or any(
                value is not None
                and (not isinstance(value, int) or value < 0)
                for value in (start_seconds, end_seconds)
            )
            or (
                start_seconds is not None
                and end_seconds is not None
                and end_seconds <= start_seconds
            )
        ):
            raise StoryboardValidationError(
                f"Storyboard {path} scene {scene_id} has invalid timing."
            )
        if any(
            not isinstance(item.get(key), list)
            or not all(isinstance(value, str) for value in item[key])
            for key in required_lists
        ):
            raise StoryboardValidationError(
                f"Storyboard {path} scene {scene_id} has invalid content fields."
            )
        if (
            item.get("transition") is not None
            and not isinstance(item.get("transition"), str)
        ):
            raise StoryboardValidationError(
                f"Storyboard {path} scene {scene_id} has an invalid transition."
            )
        scenes.append(
            StoryboardScene(
                id=scene_id,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                visual_beats=tuple(item["visual_beats"]),
                narration=tuple(item["narration"]),
                dialogue=tuple(item["dialogue"]),
                sound_cues=tuple(item["sound_cues"]),
                camera_notes=tuple(item["camera_notes"]),
                transition=item.get("transition"),
                continuity=tuple(item["continuity"]),
            )
        )
    timed_scenes = [
        scene.start_seconds is not None or scene.end_seconds is not None
        for scene in scenes
    ]
    if any(timed_scenes) and not all(timed_scenes):
        raise StoryboardValidationError(
            f"Storyboard {path} mixes timed and untimed scenes."
        )
    previous_end = None
    for scene in scenes:
        if scene.start_seconds is None:
            if previous_end is not None:
                raise StoryboardValidationError(
                    f"Storyboard {path} mixes timed and untimed scenes."
                )
            continue
        if previous_end is not None and scene.start_seconds < previous_end:
            raise StoryboardValidationError(
                f"Storyboard {path} contains overlapping or unordered scenes."
            )
        previous_end = scene.end_seconds
    duration_seconds = data.get("duration_seconds")
    if duration_seconds is not None and (
        not isinstance(duration_seconds, int) or duration_seconds < 0
    ):
        raise StoryboardValidationError(
            f"Storyboard {path} has an invalid total duration."
        )
    if scenes[0].start_seconds is None:
        if duration_seconds is not None:
            raise StoryboardValidationError(
                f"Untimed storyboard {path} cannot specify a total duration."
            )
    elif duration_seconds != scenes[-1].end_seconds:
        raise StoryboardValidationError(
            f"Storyboard {path} duration does not match its final scene."
        )
    if not isinstance(data.get("title", ""), str) or not isinstance(
        data.get("premise", ""), str
    ):
        raise StoryboardValidationError(
            f"Storyboard {path} title and premise must be strings."
        )
    return Storyboard(
        title=data.get("title", ""),
        premise=data.get("premise", ""),
        duration_seconds=duration_seconds,
        scenes=tuple(scenes),
    )


def generate_storyboard(reel_id):
    validate_reel_id(reel_id)
    reel = load_reel(reel_id)
    storyboard = build_storyboard(reel)

    GENERATED_VIDEOS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    storyboard_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_storyboard.json"
    scenes_file = GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_scenes.txt"
    storyboard_file.write_text(
        json.dumps(storyboard.to_mapping(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    scenes_file.write_text(render_storyboard(storyboard), encoding="utf-8")
    return storyboard_file


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create a validated storyboard for a saved reel."
    )
    parser.add_argument("reel_id", help="Saved reel ID, such as reel_016.")
    args = parser.parse_args(argv)

    try:
        storyboard_file = generate_storyboard(args.reel_id)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    except (ReelStorageError, StoryboardValidationError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Storyboard saved to {storyboard_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
