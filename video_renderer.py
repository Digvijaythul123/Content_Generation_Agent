import random
import subprocess
import tempfile
from pathlib import Path

from art_generator import artwork_path
from art_generator import designed_payoff, is_designed, is_video_artwork
from media_renderer import (
    build_end_card_html,
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
    reveal_style,
)
from music_library import MusicError, pick_track
from post_storage import load_post, save_post
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT


DEFAULT_DURATION_SECONDS = 8
FRAME_RATE = 30
# How far the camera pushes into the painting over the whole clip.
ZOOM_AMOUNT = 0.05
# Illustrated designs carry words near their edges, so push in gently.
DESIGNED_ZOOM_AMOUNT = 0.025
# How long the "wipe" reveal takes to slide its strip away.
WIPE_SECONDS = 1.1
TEXT_FADE_SECONDS = 0.5
# Subtle cinematic motion on the background (brightness swing, seconds per
# breath, grain strength). Kept low so the text layers stay calm and crisp.
LIGHT_BREATH = 0.025
LIGHT_PERIOD = 4
GRAIN = 3
# Optional overlay effects, after common compositing practice: depth layers
# of differing size, speed, blur, and opacity; soft streaks rather than hard
# lines; rays that fan out from one light source with dust catching the
# light; meteors that flare and fade. Each layer is drawn once as a
# transparent PNG and moved by ffmpeg, under the text.
#
# Layer: (kind, seed, count, size range, alpha range, motion). Motion is
# ("scroll", x px/s, y px/s) for a seamless loop (positive y falls),
# ("sway", px, seconds per sway, phase) for a gentle side-to-side drift,
# ("still",), or ("flash",) for meteors spread over the clip.
VIDEO_EFFECTS = {
    "sparks": (
        ("spark", 7, 70, (0.8, 4.0), (0.25, 0.85), ("scroll", 0, -46)),
        ("spark", 19, 30, (0.8, 7.3), (0.25, 0.85), ("scroll", 0, -24)),
    ),
    "meteors": (
        ("star", 23, 220, (0.5, 1.6), (0.12, 0.55), ("still",)),
        ("meteor", 5, 7, (240, 460), (0.75, 1.0), ("flash",)),
    ),
    "rain": (
        ("mist", 1, 1, (0, 0), (0.1, 0.1), ("still",)),
        ("rain", 3, 380, (22, 48), (0.22, 0.4), ("scroll", 0, 1150)),
        ("rain", 11, 160, (60, 120), (0.32, 0.55), ("scroll", 0, 1750)),
        ("raindrop", 17, 20, (180, 320), (0.14, 0.26), ("scroll", 0, 2600)),
    ),
    "snow": (
        ("snowflake", 37, 160, (1.2, 3.2), (0.35, 0.8), ("scroll", 10, 70)),
        ("snowflake", 41, 50, (3.0, 6.5), (0.25, 0.6), ("scroll", -14, 120)),
    ),
    "sunlight": (
        ("rays", 13, 16, (0.8, 3.0), (0.07, 0.19), ("sway", 34, 9, 0)),
        ("rays", 29, 10, (0.6, 2.0), (0.05, 0.13), ("sway", 26, 6.5, 2)),
        ("mote", 31, 90, (0.8, 2.6), (0.15, 0.55), ("scroll", -8, 14)),
    ),
}
EFFECT_NAMES = {
    "sparks": "Drifting sparks",
    "meteors": "Meteor shower",
    "rain": "Rain",
    "snow": "Falling snow",
    "sunlight": "Sunlight rays",
}
# Rays fan out from a sun just above the top-right corner of the frame.
_SUN = (1150, -260)
_SWAY_MARGIN = 80
_EFFECT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; width: {width}px; height: {height}px; background: transparent; }}
</style></head><body><canvas id="c" width="{width}" height="{height}"></canvas><script>
let seed = {seed};
const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const ctx = document.getElementById("c").getContext("2d");
const W = {width}, H = {height};
// A soft streak: transparent at both ends, like a motion-blurred drop.
function streak(x, y, dx, dy, width, colour, a) {{
  const g = ctx.createLinearGradient(x, y, x + dx, y + dy);
  g.addColorStop(0, `rgba(${{colour}}, 0)`);
  g.addColorStop(0.5, `rgba(${{colour}}, ${{a}})`);
  g.addColorStop(1, `rgba(${{colour}}, 0)`);
  ctx.strokeStyle = g; ctx.lineWidth = width; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + dx, y + dy); ctx.stroke();
}}
const draw = {{
  spark(x, y, r, a) {{
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3);
    g.addColorStop(0, `rgba(255, 214, 140, ${{a}})`);
    g.addColorStop(1, "rgba(255, 214, 140, 0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, r * 3, 0, Math.PI * 2); ctx.fill();
  }},
  star(x, y, r, a) {{
    if (y > 1050) return;  // stars only in the sky
    const tint = ["255, 250, 240", "225, 235, 255", "255, 238, 215"][Math.floor(rand() * 3)];
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 2.2);
    g.addColorStop(0, `rgba(${{tint}}, ${{a * (1.15 - y / 1050)}})`);
    g.addColorStop(1, `rgba(${{tint}}, 0)`);
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 2.2, 0, Math.PI * 2); ctx.fill();
  }},
  meteor(x, y, len, a) {{
    // Tapered tail, brightest at the head, trailing up and to the right.
    const ux = 0.825, uy = -0.565, tx = x + ux * len, ty = y + uy * len;
    const tint = ["255, 255, 250", "255, 255, 250", "215, 255, 225", "210, 230, 255"][Math.floor(rand() * 4)];
    const tail = (width, alpha) => {{
      const g = ctx.createLinearGradient(x, y, tx, ty);
      g.addColorStop(0, `rgba(255, 255, 255, ${{alpha}})`);
      g.addColorStop(0.12, `rgba(${{tint}}, ${{alpha * 0.8}})`);
      g.addColorStop(0.5, `rgba(${{tint}}, ${{alpha * 0.25}})`);
      g.addColorStop(1, `rgba(${{tint}}, 0)`);
      ctx.fillStyle = g; ctx.beginPath();
      ctx.moveTo(x - uy * width, y + ux * width);
      ctx.lineTo(tx, ty);
      ctx.lineTo(x + uy * width, y - ux * width);
      ctx.arc(x, y, width, 0, Math.PI * 2);
      ctx.fill();
    }};
    ctx.filter = "blur(5px)"; tail(5, a * 0.45);
    ctx.filter = "none"; tail(1.6, a);
    const h = ctx.createRadialGradient(x, y, 0, x, y, 18);
    h.addColorStop(0, `rgba(255, 255, 255, ${{a}})`);
    h.addColorStop(0.3, `rgba(${{tint}}, ${{a * 0.35}})`);
    h.addColorStop(1, `rgba(${{tint}}, 0)`);
    ctx.fillStyle = h; ctx.beginPath(); ctx.arc(x, y, 18, 0, Math.PI * 2); ctx.fill();
  }},
  rain(x, y, len, a) {{
    const angle = -0.07 + (rand() - 0.5) * 0.05;
    streak(x, y, Math.sin(-angle) * len, len, len > 60 ? 1.7 : 1.1, "220, 230, 245", a);
  }},
  raindrop(x, y, len, a) {{
    // A few large, out-of-focus drops close to the lens.
    ctx.filter = "blur(3px)";
    streak(x, y, len * 0.07, len, 5, "230, 238, 250", a);
    ctx.filter = "none";
  }},
  mist(x, y, s, a) {{
    // Rain dims and cools the air, most of all near the ground.
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, `rgba(18, 24, 34, ${{a * 0.8}})`);
    g.addColorStop(1, `rgba(28, 36, 48, ${{a * 1.3}})`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }},
  rays(x, y, spread, a) {{
    // One shaft fanning out from the sun, fading with distance.
    const [sx, sy] = [{sun_x}, {sun_y}];
    const angle = (98 + rand() * 56) * Math.PI / 180;
    const half = spread * Math.PI / 360, reach = 2600;
    ctx.save();
    ctx.filter = `blur(${{14 + spread * 8}}px)`; ctx.globalCompositeOperation = "lighter";
    const g = ctx.createRadialGradient(sx, sy, 150, sx, sy, reach);
    g.addColorStop(0, `rgba(255, 236, 190, ${{a}})`);
    g.addColorStop(0.45, `rgba(255, 222, 160, ${{a * 0.5}})`);
    g.addColorStop(1, "rgba(255, 215, 150, 0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(sx, sy);
    ctx.lineTo(sx + Math.cos(angle - half) * reach, sy + Math.sin(angle - half) * reach);
    ctx.lineTo(sx + Math.cos(angle + half) * reach, sy + Math.sin(angle + half) * reach);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }},
  snowflake(x, y, r, a) {{
    // Soft, slightly blurred flakes; bigger ones fall faster (nearer).
    ctx.filter = r > 3 ? "blur(1.6px)" : "blur(.6px)";
    ctx.fillStyle = `rgba(250, 252, 255, ${{a}})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    ctx.filter = "none";
  }},
  mote(x, y, r, a) {{
    // Dust floating in the light, brighter nearer the sun.
    const near = Math.max(0.25, 1 - Math.hypot(x - {sun_x}, y - {sun_y}) / 2000);
    ctx.filter = r > 2 ? "blur(1.5px)" : "none";
    ctx.fillStyle = `rgba(255, 240, 205, ${{a * near}})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    ctx.filter = "none";
  }},
}};
const items = [];
for (let i = 0; i < {count}; i++) items.push([
  {x_base} + rand() * {x_range}, rand() * {y_range},
  {size_low} + rand() * ({size_high} - {size_low}),
  {alpha_low} + rand() * ({alpha_high} - {alpha_low}),
]);
if ("{kind}" === "rays") {{
  const g = ctx.createRadialGradient({sun_x}, {sun_y}, 0, {sun_x}, {sun_y}, 900);
  g.addColorStop(0, `rgba(255, 238, 200, {alpha_high})`);
  g.addColorStop(1, "rgba(255, 238, 200, 0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
}}
// Repeat the 1080x1920 tile along each scrolling axis so the loop is seamless.
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


# A weather look brings its own effect unless the post chose one.
_LOOK_EFFECTS = {"monsoon_rain": "rain", "storm_clouds": "rain", "snowfall": "snow"}


def effect_for(record):
    """The record's overlay effect name, or None (legacy ``sparks: true``)."""
    effect = record.get("effect")
    if effect in VIDEO_EFFECTS:
        return effect
    if "effect" not in record and not record.get("sparks") and record.get("weather_look"):
        return _LOOK_EFFECTS.get(record.get("weather"))
    return "sparks" if record.get("sparks") and effect is None else None


METEOR_SECONDS = 0.7
METEOR_FADE_SECONDS = 0.18
_METEOR_TILE = (500, 360)
_METEOR_HEAD = (24, 336)
_METEOR_VARIANTS = 3


def _meteor_events(strips, seed, count, seconds=DEFAULT_DURATION_SECONDS):
    """Shooting stars: each flares across the upper sky once, then fades."""
    rand = random.Random(seed)
    gap = seconds / count
    events = []
    for index in range(count):
        start = round(index * gap + rand.uniform(0.1, gap * 0.6), 2)
        speed = rand.uniform(0.8, 1.25)
        vx, vy = round(900 * speed), round(620 * speed)
        x = rand.randint(380, 1180)
        y = rand.randint(-260, 200)
        events.append((
            strips[index % len(strips)],
            f"{x}-{vx}*(t-{start})",
            f"{y}+{vy}*(t-{start})",
            (start, METEOR_SECONDS),
        ))
    return events


def _layer_html(kind, seed, count, size, alpha, width, height, x_offsets, y_offsets, x_base=0):
    # x_base shifts the scene (and the sun) right on canvases wider than the frame.
    return _EFFECT_HTML.format(
        width=width, height=height, seed=seed, count=count, kind=kind,
        size_low=size[0], size_high=size[1],
        alpha_low=alpha[0], alpha_high=alpha[1],
        x_base=x_base, x_range=1080, y_range=1920,
        x_offsets=x_offsets, y_offsets=y_offsets,
        sun_x=_SUN[0] + x_base, sun_y=_SUN[1],
    )


def render_effect_layers(effect, folder, seconds=DEFAULT_DURATION_SECONDS):
    """Draw an effect's layers: (path, x expr, y expr[, (start, seconds)])."""
    layers = []
    for index, (kind, seed, count, size, alpha, motion) in enumerate(VIDEO_EFFECTS[effect]):
        name = folder / f"{effect}_{index}"
        if motion[0] == "flash":
            strips = []
            for variant in range(_METEOR_VARIANTS):
                width, height = _METEOR_TILE
                length = size[0] + (size[1] - size[0]) * variant / max(_METEOR_VARIANTS - 1, 1)
                html = _layer_html(
                    kind, seed + variant, 1, (length, length), (alpha[1], alpha[1]),
                    width, height, "[0]", "[0]",
                ).replace(
                    "rand() * 1080, rand() * 1920,",
                    f"{_METEOR_HEAD[0]}, {_METEOR_HEAD[1]},",
                )
                strips.append(render_html_to_png(html, Path(f"{name}_{variant}.png"), (width, height)))
            layers += _meteor_events(strips, seed, count, seconds)
            continue
        if motion[0] == "sway":
            _, amount, period, phase = motion
            width, height = 1080 + 2 * _SWAY_MARGIN, 1920
            html = _layer_html(
                kind, seed, count, size, alpha, width, height, "[0]", "[0]",
                x_base=_SWAY_MARGIN,
            )
            x = f"-{_SWAY_MARGIN}+{amount}*sin(2*PI*t/{period}+{phase})"
            y = "0"
        else:
            vx, vy = motion[1:] if motion[0] == "scroll" else (0, 0)
            width = 2160 if vx else 1080
            height = 3840 if vy else 1920
            html = _layer_html(
                kind, seed, count, size, alpha, width, height,
                "[-1080, 0, 1080, 2160]" if vx else "[-1080, 0, 1080]" if kind != "mist" else "[0]",
                "[-1920, 0, 1920, 3840]" if vy else "[0]",
            )
            x, y = _scroll(vx, 1080), _scroll(vy, 1920)
        strip = render_html_to_png(html, Path(f"{name}.png"), (width, height))
        layers.append((strip, x, y))
    return layers


# Hook first, payoff later: the hook is on screen from the first frame,
# alone long enough to read and wonder (about 3 seconds), and the payoff
# arrives after it, so viewers wait for it instead of scrolling on.
TEXT_REVEALS = (("title", 0), ("quote", 2.0), ("takeaway", 4.5))
# Posters have no title on screen: the quote is the hook from frame one.
POSTER_REVEALS = (("quote", 0), ("takeaway", 3.5))
# The closing line gets its own end card after the main Reel: the picture
# cross-fades into it over END_CARD_FADE seconds and it stays on screen.
END_CARD_SECONDS = 2.2
END_CARD_FADE = 0.6


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
    zoom=ZOOM_AMOUNT,
    end_card=None,
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
        f"vignette=angle=PI/8,noise=alls={GRAIN}:allf=t[vbase]"
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
            f"zoompan=z='1+{zoom}*on/{frames}':"
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
    for offset, (strip, x, y, *flash) in enumerate(effects):
        index = first_effect + offset
        label = "v0" if offset == len(effects) - 1 else f"ve{offset}"
        source, timing = f"{index}:v", ""
        if flash:
            # A timed flash (a meteor) flares in and fades out.
            start, length = flash[0]
            fade_out = round(start + length - METEOR_FADE_SECONDS, 2)
            filters.append(
                f"[{index}:v]format=rgba,"
                f"fade=t=in:st={start}:d={METEOR_FADE_SECONDS / 2}:alpha=1,"
                f"fade=t=out:st={fade_out}:d={METEOR_FADE_SECONDS}:alpha=1[fx{offset}]"
            )
            source = f"fx{offset}"
            timing = f":enable='between(t,{start},{round(start + length, 2)})'"
        filters.append(
            f"[{previous}][{source}]overlay=x='{x}':y='{y}':format=auto{timing}[{label}]"
        )
        previous = label
    if not effects:
        filters[0] = filters[0].replace("[vbase]", "[v0]")
    for index, (layer, start, *hide) in enumerate(text_layers, start=1):
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
        position = "0:0"
        if hide and len(hide) > 1 and hide[1] == "wipe":
            # A strip that slides off to the right, uncovering the line from
            # its first word to its last.
            at = hide[0]
            position = (
                f"x='if(lt(t,{at}),0,min({width},({width}+60)*(t-{at})/{WIPE_SECONDS}))':y=0"
            )
        elif hide:
            # A veil that clears to reveal what is beneath it.
            fade += f",fade=t=out:st={hide[0]}:d={TEXT_FADE_SECONDS}:alpha=1"
        filters.append(f"[{index}:v]format=rgba{fade}[t{index}]")
        filters.append(f"[v{index - 1}][t{index}]overlay={position}[v{index}]")
    total = seconds + (END_CARD_SECONDS - END_CARD_FADE if end_card else 0)
    filters.append(
        f"[v{len(text_layers)}]scale=out_range=tv,format=yuv420p"
        + (f",fps={FRAME_RATE},settb=1/{FRAME_RATE}[main]" if end_card else "[out]")
    )
    for strip, *_ in effects:
        inputs += [
            "-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(seconds),
            "-i", str(strip),
        ]
    if end_card:
        card = len(text_layers) + len(effects) + 1
        inputs += [
            "-loop", "1", "-framerate", str(FRAME_RATE), "-t", str(END_CARD_SECONDS),
            "-i", str(end_card),
        ]
        filters.append(
            f"[{card}:v]scale={width}:{height},setsar=1,scale=out_range=tv,"
            f"format=yuv420p,fps={FRAME_RATE},settb=1/{FRAME_RATE}[card]"
        )
        filters.append(
            f"[main][card]xfade=transition=fade:duration={END_CARD_FADE}:"
            f"offset={round(seconds - END_CARD_FADE, 2)}[out]"
        )
    audio = ["-an"]
    if music is not None:
        # Loop short tracks, then fade in and out so the Reel loops cleanly.
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        # Skip a silent intro, even out loudness for phone speakers, then
        # fade in and out so the Reel loops cleanly.
        filters.append(
            f"[{len(text_layers) + len(effects) + (2 if end_card else 1)}:a]"
            "silenceremove=start_periods=1:start_threshold=-45dB,"
            f"atrim=0:{total},asetpts=PTS-STARTPTS,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            "afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={max(total - 1.5, 0)}:d=1.5[aout]"
        )
        audio = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
    return [
        ffmpeg, "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]", *audio,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        # 4:2:0 High profile plays everywhere; the end-card crossfade would
        # otherwise switch the encoder to 4:4:4, which Safari and many phones
        # cannot play.
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        # Cap the bitrate: grain on busy clips can otherwise bloat the file.
        "-maxrate", "12M", "-bufsize", "24M",
        "-color_range", "tv", "-r", str(FRAME_RATE), "-t", str(total),
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
    designed = is_designed(record)
    with tempfile.TemporaryDirectory() as folder:
        chrome = []
        if designed:
            # The art already carries the words: move the whole picture.
            if motion_clip:
                artwork = extract_video_frame(artwork, Path(folder) / "frame.png")
                motion_clip = False
            background = render_html_to_jpeg(
                build_post_html(record, brand, artwork, layer="background"),
                Path(folder) / "background.jpg",
                IMAGE_REEL_SIZE,
            )
        elif motion_clip:
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
        designed_layers = []
        if designed and designed_payoff(record) and reveal_style(record) != "none":
            # The answer is drawn in the picture: veil it, then clear the veil.
            designed_layers = [(
                render_html_to_png(
                    build_post_html(record, brand, artwork, layer="veil"),
                    Path(folder) / "veil.png",
                    IMAGE_REEL_SIZE,
                ),
                0,
                POSTER_REVEALS[1][1],
                reveal_style(record),
            )]

        text_layers = designed_layers if designed else chrome + [
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
        end_card = None
        if str(record.get("cta") or "").strip():
            end_card = render_html_to_jpeg(
                build_end_card_html(record, brand, artwork),
                Path(folder) / "end_card.jpg",
                IMAGE_REEL_SIZE,
            )
        command = build_ffmpeg_command(
            ffmpeg_executable(),
            background,
            text_layers,
            output,
            seconds,
            music,
            motion_clip=motion_clip,
            # Crop the bottom strip where tools put watermarks.
            clip_zoom=1.06,
            effects=(
                render_effect_layers(effect_for(record), Path(folder), seconds)
                if effect_for(record)
                else ()
            ),
            zoom=DESIGNED_ZOOM_AMOUNT if designed else ZOOM_AMOUNT,
            end_card=end_card,
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
