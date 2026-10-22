import random
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
# Optional overlay effects. Each layer is drawn once as a tileable
# transparent PNG and scrolled by ffmpeg so it loops seamlessly under the
# text: (kind, seed, count, size range, alpha range, x and y speed in px/s;
# positive y falls, negative y rises). For "meteor", count is the number of
# shooting stars spread over the clip.
VIDEO_EFFECTS = {
    "sparks": (
        ("spark", 7, 70, (0.8, 4.0), (0.25, 0.85), 0, -46),
        ("spark", 19, 30, (0.8, 7.3), (0.25, 0.85), 0, -24),
    ),
    "meteors": (
        ("star", 23, 160, (0.6, 1.8), (0.15, 0.6), 0, 0),
        # Meteors are timed flashes across the sky, not a looping layer.
        ("meteor", 5, 7, (260, 420), (0.7, 0.95), -900, 620),
    ),
    "rain": (
        ("rain", 3, 150, (40, 90), (0.18, 0.35), 0, 1500),
        ("rain", 11, 60, (90, 170), (0.3, 0.5), 0, 2300),
    ),
    "sunlight": (
        ("beam", 13, 4, (120, 260), (0.10, 0.20), 14, 0),
        ("beam", 29, 3, (80, 180), (0.08, 0.16), -9, 0),
    ),
}
EFFECT_NAMES = {
    "sparks": "Drifting sparks",
    "meteors": "Meteor shower",
    "rain": "Rain",
    "sunlight": "Sunlight rays",
}
_EFFECT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; width: {width}px; height: {height}px; background: transparent; }}
</style></head><body><canvas id="c" width="{width}" height="{height}"></canvas><script>
let seed = {seed};
const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const ctx = document.getElementById("c").getContext("2d");
const draw = {{
  spark(x, y, r, a) {{
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3);
    g.addColorStop(0, `rgba(255, 214, 140, ${{a}})`);
    g.addColorStop(1, "rgba(255, 214, 140, 0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, r * 3, 0, Math.PI * 2); ctx.fill();
  }},
  star(x, y, r, a) {{
    if (y > 1100) return;  // stars only in the sky
    ctx.fillStyle = `rgba(255, 250, 235, ${{a}})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }},
  meteor(x, y, len, a) {{
    // The tail trails up and to the right of the head, against the motion.
    const tx = x + 0.825 * len, ty = y - 0.565 * len;
    const g = ctx.createLinearGradient(x, y, tx, ty);
    g.addColorStop(0, `rgba(255, 248, 225, ${{a}})`);
    g.addColorStop(0.15, `rgba(255, 220, 160, ${{a * 0.6}})`);
    g.addColorStop(1, "rgba(255, 210, 150, 0)");
    ctx.strokeStyle = g; ctx.lineWidth = 3; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(tx, ty); ctx.stroke();
    const h = ctx.createRadialGradient(x, y, 0, x, y, 14);
    h.addColorStop(0, `rgba(255, 255, 240, ${{a}})`);
    h.addColorStop(1, "rgba(255, 255, 240, 0)");
    ctx.fillStyle = h; ctx.beginPath(); ctx.arc(x, y, 14, 0, Math.PI * 2); ctx.fill();
  }},
  rain(x, y, len, a) {{
    ctx.strokeStyle = `rgba(215, 228, 255, ${{a}})`;
    ctx.lineWidth = len > 90 ? 2.2 : 1.4; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - len * 0.06, y + len); ctx.stroke();
  }},
  beam(x, y, w, a) {{
    // A soft shaft of light falling from above, leaning slightly.
    ctx.save();
    ctx.filter = "blur(28px)";
    ctx.globalCompositeOperation = "lighter";
    ctx.translate(x, -120); ctx.rotate(-0.32);
    const g = ctx.createLinearGradient(0, 0, 0, 2100);
    g.addColorStop(0, `rgba(255, 228, 165, ${{a}})`);
    g.addColorStop(0.55, `rgba(255, 220, 150, ${{a * 0.45}})`);
    g.addColorStop(1, "rgba(255, 220, 150, 0)");
    ctx.fillStyle = g; ctx.fillRect(-w / 2, 0, w, 2100);
    ctx.restore();
  }},
}};
const items = [];
for (let i = 0; i < {count}; i++) items.push([
  rand() * 1080, rand() * 1920,
  {size_low} + rand() * ({size_high} - {size_low}),
  {alpha_low} + rand() * ({alpha_high} - {alpha_low}),
]);
// Repeat the 1080x1920 tile along each moving axis so the scroll loops.
for (const ox of {x_offsets}) for (const oy of {y_offsets})
  for (const [x, y, s, a] of items) draw.{kind}(x + ox, y + oy, s, a);
</script></body></html>"""


def _scroll(speed, period):
    """ffmpeg overlay position that scrolls a doubled tile by ``speed``."""
    if speed > 0:
        return f"-{period}+mod(t*{speed},{period})"
    if speed < 0:
        return f"-mod(t*{-speed},{period})"
    return "0"


def effect_for(record):
    """The record's overlay effect name, or None (legacy ``sparks: true``)."""
    effect = record.get("effect")
    if effect in VIDEO_EFFECTS:
        return effect
    return "sparks" if record.get("sparks") and effect is None else None


METEOR_SECONDS = 0.6
_METEOR_TILE = (480, 340)


def _meteor_events(strip, seed, count, speed, seconds=DEFAULT_DURATION_SECONDS):
    """Shooting stars: each crosses the upper sky once, then disappears."""
    vx, vy = speed
    rand = random.Random(seed)
    gap = seconds / count
    events = []
    for index in range(count):
        start = round(index * gap + rand.uniform(0.1, gap * 0.6), 2)
        x = rand.randint(380, 1180)
        y = rand.randint(-260, 200)
        events.append((
            strip,
            f"{x}-{-vx}*(t-{start})",
            f"{y}+{vy}*(t-{start})",
            f"between(t,{start},{round(start + METEOR_SECONDS, 2)})",
        ))
    return events


def render_effect_layers(effect, folder, seconds=DEFAULT_DURATION_SECONDS):
    """Draw an effect's layers as PNG strips: (path, x expr, y expr[, enable])."""
    layers = []
    for index, (kind, seed, count, size, alpha, vx, vy) in enumerate(VIDEO_EFFECTS[effect]):
        if kind == "meteor":
            width, height = _METEOR_TILE
            html = _EFFECT_HTML.format(
                width=width, height=height, seed=seed, count=1, kind=kind,
                size_low=size[1], size_high=size[1],
                alpha_low=alpha[1], alpha_high=alpha[1],
                x_offsets="[0]", y_offsets="[0]",
            ).replace("rand() * 1080, rand() * 1920,", "16, 324,")
            strip = render_html_to_png(
                html, folder / f"{effect}_{index}.png", (width, height)
            )
            layers += _meteor_events(strip, seed, count, (vx, vy), seconds)
            continue
        width = 2160 if vx else 1080
        height = 3840 if vy else 1920
        x_offsets = "[-1080, 0, 1080, 2160]" if vx else "[-1080, 0, 1080]"
        y_offsets = "[-1920, 0, 1920, 3840]" if vy else "[0]"
        html = _EFFECT_HTML.format(
            width=width, height=height, seed=seed, count=count, kind=kind,
            size_low=size[0], size_high=size[1],
            alpha_low=alpha[0], alpha_high=alpha[1],
            x_offsets=x_offsets, y_offsets=y_offsets,
        )
        strip = render_html_to_png(
            html, folder / f"{effect}_{index}.png", (width, height)
        )
        layers.append((strip, _scroll(vx, 1080), _scroll(vy, 1920)))
    return layers


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
    effects=(),
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
        f"vignette=angle=PI/5,noise=alls={GRAIN}:allf=t[vbase]"
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
    # Effects move over the background but stay under the glow and text.
    previous = "vbase"
    first_effect = len(text_layers) + 1
    for offset, (strip, x, y, *enable) in enumerate(effects):
        index = first_effect + offset
        label = "v0" if offset == len(effects) - 1 else f"ve{offset}"
        timing = f":enable='{enable[0]}'" if enable else ""
        filters.append(
            f"[{previous}][{index}:v]overlay=x='{x}':y='{y}':format=auto{timing}[{label}]"
        )
        previous = label
    if not effects:
        filters[0] = filters[0].replace("[vbase]", "[v0]")
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
    for strip, *_ in effects:
        inputs += [
            "-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(seconds),
            "-i", str(strip),
        ]
    audio = ["-an"]
    if music is not None:
        # Loop short tracks, then fade in and out so the Reel loops cleanly.
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        # Skip a silent intro, even out loudness for phone speakers, then
        # fade in and out so the Reel loops cleanly.
        filters.append(
            f"[{len(text_layers) + len(effects) + 1}:a]"
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
            effects=(
                render_effect_layers(effect_for(record), Path(folder), seconds)
                if effect_for(record)
                else ()
            ),
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
