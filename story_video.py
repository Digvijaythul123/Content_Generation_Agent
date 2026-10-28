"""Story videos: a ~30-second Reel made of four 8-second Google Flow shots.

Each shot is filmed separately in Flow and uploaded here; the renderer joins
them with soft crossfades, times a caption to each shot (the title over the
first), mixes the clips' own sound under the music, and ends on the closing
card. Shot 1 also serves as the post's artwork, so the cover image and the
rest of the pipeline work as for any Reel.
"""

import subprocess
import tempfile
from pathlib import Path
from string import Template

from art_generator import (
    ArtGenerationError,
    MAX_VIDEO_ARTWORK_BYTES,
    detect_video_type,
    save_post_artwork,
)
from media_renderer import (
    IMAGE_REEL_SIZE,
    MediaRenderError,
    TEMPLATE_DIRECTORY,
    _brand_for,
    _copy_html,
    build_end_card_html,
    extract_video_frame,
    ffmpeg_executable,
    render_html_to_jpeg,
    render_html_to_png,
)
from music_library import MusicError, pick_track
from post_storage import load_post, save_post
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT

SHOT_COUNT = 4
SHOT_SECONDS = 8
CROSSFADE = 0.6
CAPTION_FADE = 0.4
END_CARD_SECONDS = 2.2
END_CARD_FADE = 0.6
FRAME_RATE = 30
MUSIC_LEVEL = 0.7
CLIP_SOUND_LEVEL = 0.6
CAPTION_TEMPLATE = TEMPLATE_DIRECTORY / "story_caption.html"
_SHOT_SUFFIXES = (".mp4", ".mov")


def is_story_video(record):
    return bool(record.get("story_video"))


def shot_path(post_id, number):
    """The uploaded clip for one shot, or None."""
    for suffix in _SHOT_SUFFIXES:
        path = GENERATED_ASSETS_DIRECTORY / f"{post_id}_shot{number}{suffix}"
        if path.is_file():
            return path
    return None


def shots_ready(post_id, count=SHOT_COUNT):
    """Numbers of the shots uploaded so far."""
    return [number for number in range(1, count + 1) if shot_path(post_id, number)]


def save_shot(post_id, number, data):
    """Store one uploaded shot; shot 1 also becomes the post's artwork."""
    record = load_post(post_id)
    if not is_story_video(record):
        raise ArtGenerationError("Only story videos take numbered shots.")
    count = len(record.get("story_shots") or []) or SHOT_COUNT
    if not 1 <= number <= count:
        raise ArtGenerationError(f"Shot must be between 1 and {count}.")
    kind = detect_video_type(data)
    if kind is None:
        raise ArtGenerationError("Each shot must be an MP4 or MOV clip.")
    if len(data) > MAX_VIDEO_ARTWORK_BYTES:
        raise ArtGenerationError("Each shot must be 80 MB or smaller.")
    suffix = ".mov" if kind == "video/quicktime" else ".mp4"
    old = shot_path(post_id, number)
    GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output = GENERATED_ASSETS_DIRECTORY / f"{post_id}_shot{number}{suffix}"
    output.write_bytes(data)
    if old is not None and old != output:
        old.unlink(missing_ok=True)
    if number == 1:
        save_post_artwork(post_id, data)
    return output


def _clip_info(path):
    """(duration, has sound) of a clip."""
    import re

    result = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    )
    found = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr)
    duration = None
    if found:
        hours, minutes, seconds = found.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return duration, bool(re.search(r"Stream #\S+.*: Audio:", result.stderr))


def caption_html(text, kind):
    source = CAPTION_TEMPLATE.read_text(encoding="utf-8")
    return Template(source).substitute(text=_copy_html(text), kind=kind)


def shot_timeline(lengths, crossfade=CROSSFADE):
    """Start time of each shot in the joined video, and the total length."""
    starts, position = [], 0.0
    for index, length in enumerate(lengths):
        starts.append(round(position, 2))
        position += length - (crossfade if index < len(lengths) - 1 else 0)
    return starts, round(position, 2)


def build_story_command(ffmpeg, clips, captions, output, music=None, end_card=None):
    """ffmpeg arguments for a story video.

    ``clips`` is [(path, seconds, has_sound)]; ``captions`` is
    [(png, start, end)] shown over the joined shots; ``end_card`` is a still
    crossfaded in at the end.
    """
    width, height = IMAGE_REEL_SIZE
    lengths = [seconds for _, seconds, _ in clips]
    starts, story_length = shot_timeline(lengths)
    total = round(story_length + (END_CARD_SECONDS - END_CARD_FADE if end_card else 0), 2)
    inputs, filters = [], []
    for index, (path, seconds, _) in enumerate(clips):
        inputs += ["-i", str(path)]
        # Fill the frame and crop a little from the bottom, where video tools
        # put their watermark.
        filters.append(
            f"[{index}:v]scale={round(width * 1.06)}:{round(height * 1.06)}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-{width})/2:0,"
            f"setsar=1,trim=0:{seconds},setpts=PTS-STARTPTS,format=yuv420p,"
            f"fps={FRAME_RATE},settb=1/{FRAME_RATE}[s{index}]"
        )
    joined = "s0"
    for index in range(1, len(clips)):
        offset = round(starts[index], 2)
        label = f"j{index}"
        filters.append(
            f"[{joined}][s{index}]xfade=transition=fade:duration={CROSSFADE}:"
            f"offset={offset}[{label}]"
        )
        joined = label
    previous = joined
    for number, (png, start, end) in enumerate(captions):
        index = len(clips) + number
        inputs += ["-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(story_length), "-i", str(png)]
        fade_out = round(max(start, end - CAPTION_FADE), 2)
        filters.append(
            f"[{index}:v]format=rgba,"
            f"fade=t=in:st={start}:d={CAPTION_FADE}:alpha=1,"
            f"fade=t=out:st={fade_out}:d={CAPTION_FADE}:alpha=1[c{number}]"
        )
        label = f"o{number}"
        filters.append(f"[{previous}][c{number}]overlay=0:0:format=auto[{label}]")
        previous = label
    filters.append(f"[{previous}]format=yuv420p,fps={FRAME_RATE},settb=1/{FRAME_RATE}[story]")
    next_input = len(clips) + len(captions)
    if end_card:
        inputs += ["-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(END_CARD_SECONDS), "-i", str(end_card)]
        filters.append(
            f"[{next_input}:v]scale={width}:{height},setsar=1,format=yuv420p,"
            f"fps={FRAME_RATE},settb=1/{FRAME_RATE}[card]"
        )
        filters.append(
            f"[story][card]xfade=transition=fade:duration={END_CARD_FADE}:"
            f"offset={round(story_length - END_CARD_FADE, 2)}[out]"
        )
        next_input += 1
    else:
        filters.append("[story]null[out]")
    # The clips' own sound, crossfaded shot to shot (silence for a clip
    # without sound), padded under the end card.
    for index, (_, seconds, has_sound) in enumerate(clips):
        source = (
            f"[{index}:a]atrim=0:{seconds},asetpts=PTS-STARTPTS,"
            if has_sound
            else f"anullsrc=r=44100:cl=stereo,atrim=0:{seconds},"
        )
        filters.append(f"{source}aresample=44100,aformat=channel_layouts=stereo[a{index}]")
    sound = "a0"
    for index in range(1, len(clips)):
        label = f"x{index}"
        filters.append(f"[{sound}][a{index}]acrossfade=d={CROSSFADE}[{label}]")
        sound = label
    filters.append(f"[{sound}]apad=whole_dur={total},volume={CLIP_SOUND_LEVEL}[amb]")
    fades = f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(total - 1.5, 0)}:d=1.5"
    if music is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(
            f"[{next_input}:a]silenceremove=start_periods=1:start_threshold=-45dB,"
            f"atrim=0:{total},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"aresample=44100,volume={MUSIC_LEVEL}[mus]"
        )
        filters.append(f"[mus][amb]amix=inputs=2:duration=first:normalize=0,{fades}[aout]")
    else:
        filters.append(f"[amb]loudnorm=I=-16:TP=-1.5:LRA=11,{fades}[aout]")
    return [
        ffmpeg, "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[out]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-maxrate", "12M", "-bufsize", "24M",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-r", str(FRAME_RATE), "-t", str(total),
        "-movflags", "+faststart",
        str(output),
    ]


def render_story_video(post_id, output):
    """Join the uploaded shots into the post's Reel video."""
    record = load_post(post_id)
    shots = record.get("story_shots") or []
    if not shots:
        raise MediaRenderError("Write the story script before rendering.")
    missing = [number for number in range(1, len(shots) + 1) if shot_path(post_id, number) is None]
    if missing:
        raise MediaRenderError(
            "Upload every shot first; missing shot " + ", ".join(map(str, missing)) + "."
        )
    clips = []
    for number in range(1, len(shots) + 1):
        path = shot_path(post_id, number)
        length, has_sound = _clip_info(path)
        if not length or length < 2:
            raise MediaRenderError(f"Shot {number} is too short or unreadable.")
        clips.append((path, round(min(length - 0.05, SHOT_SECONDS), 2), has_sound))
    starts, story_length = shot_timeline([seconds for _, seconds, _ in clips])
    try:
        music = pick_track(record)
    except MusicError as error:
        raise MediaRenderError(str(error)) from error
    brand = _brand_for(record)
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        captions = []
        title = str(record.get("title") or "").strip()
        if title:
            # The title names the story over the opening shot, as the hook.
            captions.append((
                render_html_to_png(caption_html(title, "title"), folder / "title.png", IMAGE_REEL_SIZE),
                0,
                round(starts[1] if len(starts) > 1 else story_length, 2),
            ))
        for number, shot in enumerate(shots):
            start = starts[number] + (0.5 if number == 0 else CROSSFADE / 2)
            end = (starts[number + 1] + CROSSFADE / 2) if number + 1 < len(starts) else story_length
            captions.append((
                render_html_to_png(
                    caption_html(shot["caption"], "caption"),
                    folder / f"caption_{number + 1}.png",
                    IMAGE_REEL_SIZE,
                ),
                round(start, 2),
                round(end, 2),
            ))
        end_card = None
        if str(record.get("cta") or "").strip():
            last_frame = extract_video_frame(clips[-1][0], folder / "last.png")
            end_card = render_html_to_jpeg(
                build_end_card_html(record, brand, last_frame), folder / "end_card.jpg", IMAGE_REEL_SIZE
            )
        command = build_story_command(
            ffmpeg_executable(), clips, captions, output, music=music, end_card=end_card
        )
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
        except subprocess.CalledProcessError as error:
            raise MediaRenderError(
                f"ffmpeg could not render the story video: {error.stderr.strip()}"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise MediaRenderError("ffmpeg took longer than 15 minutes.") from error
    try:
        record["video_path"] = str(output.relative_to(PROJECT_ROOT))
    except ValueError:
        record["video_path"] = str(output)
    record["video_music"] = music.name if music else None
    save_post(post_id, record)
    return output
