import subprocess
import tempfile
from pathlib import Path

from art_generator import artwork_path
from art_generator import is_video_artwork
from media_renderer import (
    IMAGE_REEL_SIZE,
    extract_video_frame,
    ffmpeg_executable,
    reel_layout,
    MediaRenderError,
    _brand_for,
    build_post_html,
    is_image_reel,
    render_html_to_jpeg,
    render_html_to_png,
)
from music_library import MusicError, pick_track
from post_storage import load_post, save_post
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT


DEFAULT_DURATION_SECONDS = 8
FRAME_RATE = 30
# How far the camera pushes into the painting over the whole clip.
ZOOM_AMOUNT = 0.08
TEXT_FADE_SECONDS = 0.5
# Subtle cinematic motion on the background (brightness swing, seconds per
# breath, grain strength). Kept low so the text layers stay calm and crisp.
LIGHT_BREATH = 0.025
LIGHT_PERIOD = 4
GRAIN = 6
# The hook is on screen from the first frame (average watch time was ~2.6s),
# then the main line and the payoff follow quickly.
TEXT_REVEALS = (("title", 0), ("quote", 0.8), ("takeaway", 2.5))
# Posters have no title on screen: the quote is the hook from frame one.
POSTER_REVEALS = (("quote", 0), ("takeaway", 1.5))


def reel_video_path(post_id):
    return GENERATED_ASSETS_DIRECTORY / f"{post_id}_reel.mp4"


def build_ffmpeg_command(
    ffmpeg,
    background,
    text_layers,
    output,
    seconds=DEFAULT_DURATION_SECONDS,
    music=None,
    motion_clip=False,
    clip_zoom=1.0,
):
    """Return the ffmpeg arguments for a Reel.

    ``background`` is a still image (given a slow push-in) or, with
    ``motion_clip``, a video that is looped or trimmed to length and cropped
    from the top by ``clip_zoom`` (hiding a bottom watermark).
    ``text_layers`` is a sequence of (transparent PNG, start second) pairs;
    each layer fades in at its own start time over the moving background.
    """
    width, height = IMAGE_REEL_SIZE
    frames = seconds * FRAME_RATE
    # Free "film finish": light that breathes, a soft vignette, and fine
    # moving grain, so the background feels like a shot from a film.
    finish = (
        f"eq=eval=frame:brightness='{LIGHT_BREATH}*sin(2*PI*t/{LIGHT_PERIOD})',"
        f"vignette=angle=PI/5,noise=alls={GRAIN}:allf=t[v0]"
    )
    if motion_clip:
        top = "0" if clip_zoom > 1 else f"(ih-{height})/2"
        filters = [
            f"[0:v]scale={round(width * clip_zoom)}:{round(height * clip_zoom)}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-{width})/2:{top},"
            f"fps={FRAME_RATE},setsar=1,{finish}"
        ]
        inputs = ["-stream_loop", "-1", "-t", str(seconds), "-i", str(background)]
    else:
        # Upscaling before zoompan keeps the slow push-in from jittering.
        filters = [
            f"[0:v]scale={width * 2}:{height * 2},"
            f"zoompan=z='1+{ZOOM_AMOUNT}*on/{frames}':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={FRAME_RATE},{finish}"
        ]
        inputs = [
            "-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(seconds),
            "-i", str(background),
        ]
    for index, (layer, start) in enumerate(text_layers, start=1):
        inputs += [
            "-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(seconds),
            "-i", str(layer),
        ]
        # A layer due at 0s is shown at full strength on the very first frame.
        fade = (
            f",fade=t=in:st={start}:d={TEXT_FADE_SECONDS}:alpha=1"
            if start > 0
            else ""
        )
        filters.append(f"[{index}:v]format=rgba{fade}[t{index}]")
        filters.append(f"[v{index - 1}][t{index}]overlay=0:0[v{index}]")
    filters.append(
        f"[v{len(text_layers)}]scale=out_range=tv,format=yuv420p[out]"
    )
    audio = ["-an"]
    if music is not None:
        # Loop short tracks, then fade in and out so the Reel loops cleanly.
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        # Skip a silent intro, even out loudness for phone speakers, then
        # fade in and out so the Reel loops cleanly.
        filters.append(
            f"[{len(text_layers) + 1}:a]"
            "silenceremove=start_periods=1:start_threshold=-45dB,"
            f"atrim=0:{seconds},asetpts=PTS-STARTPTS,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            "afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={max(seconds - 1.5, 0)}:d=1.5[aout]"
        )
        audio = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
    return [
        ffmpeg, "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]", *audio,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        # Cap the bitrate: grain on busy clips can otherwise bloat the file.
        "-maxrate", "12M", "-bufsize", "24M",
        "-color_range", "tv", "-r", str(FRAME_RATE), "-t", str(seconds),
        "-movflags", "+faststart",
        str(output),
    ]


def render_image_reel_video(post_id, seconds=DEFAULT_DURATION_SECONDS):
    """Render an approved one-image Reel to a silent 1080x1920 MP4."""
    record = load_post(post_id)
    if not is_image_reel(record):
        raise MediaRenderError("Only one-image Reels can be rendered as video.")
    artwork = artwork_path(post_id)
    if artwork is None:
        raise MediaRenderError("Generate or add the artwork before the video.")
    brand = _brand_for(record)
    try:
        music = pick_track(record)
    except MusicError as error:
        raise MediaRenderError(str(error)) from error
    output = reel_video_path(post_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    motion_clip = is_video_artwork(artwork)
    poster = reel_layout(record) == "poster"
    with tempfile.TemporaryDirectory() as folder:
        chrome = []
        if motion_clip:
            # The clip itself moves; overlay only the glow and fades on it.
            clip = artwork
            artwork = extract_video_frame(clip, Path(folder) / "frame.png")
            background = clip
            chrome = [(
                render_html_to_png(
                    build_post_html(record, brand, artwork, layer="chrome"),
                    Path(folder) / "chrome.png",
                    IMAGE_REEL_SIZE,
                ),
                0,
            )]
        else:
            background = render_html_to_jpeg(
                build_post_html(record, brand, artwork, layer="background"),
                Path(folder) / "background.jpg",
                IMAGE_REEL_SIZE,
            )
        text_layers = chrome + [
            (
                render_html_to_png(
                    build_post_html(
                        record, brand, artwork, layer=f"text only-{part}"
                    ),
                    Path(folder) / f"text_{part}.png",
                    IMAGE_REEL_SIZE,
                ),
                start,
            )
            for part, start in (POSTER_REVEALS if poster else TEXT_REVEALS)
        ]
        command = build_ffmpeg_command(
            ffmpeg_executable(),
            background,
            text_layers,
            output,
            seconds,
            music,
            motion_clip=motion_clip,
            # Posters crop the bottom strip where tools put watermarks.
            clip_zoom=1.11 if poster else 1.0,
        )
        try:
            subprocess.run(
                command, check=True, capture_output=True, text=True, timeout=600
            )
        except subprocess.CalledProcessError as error:
            raise MediaRenderError(
                f"ffmpeg could not render the Reel: {error.stderr.strip()}"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise MediaRenderError("ffmpeg took longer than 10 minutes.") from error
    try:
        record["video_path"] = str(output.relative_to(PROJECT_ROOT))
    except ValueError:
        record["video_path"] = str(output)
    record["video_music"] = music.name if music else None
    save_post(post_id, record)
    return output
