"""Check a Flow story clip against its script after upload.

Flow sometimes changes the narration or runs long. The clip's audio is
transcribed with Gemini (free tier) and compared with the script's spoken
lines, so the review page can say "narration matches" before rendering.
A failed check never blocks anything; it is only advice.
"""

import base64
import re
import subprocess
import tempfile
from pathlib import Path

from ai_service import AIServiceError, transcribe_audio


# Share of the script's words that must be heard for a match.
MATCH_SHARE = 0.85
CLIP_SECONDS = (8.5, 11.0)
_SPOKEN = re.compile(r'(?:Narrator|Young monk|The Buddha):\s*"(.*)"\s*$', re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9']+")


def script_words(script):
    """The words the script says out loud, in order."""
    spoken = []
    for line in str(script or "").splitlines():
        if not line.startswith("Scene "):
            continue
        match = _SPOKEN.search(line)
        if match:
            spoken.append(match.group(1))
    return _WORD.findall(" ".join(spoken).lower())


def compare(script, transcript, seconds=None):
    """Compare the script's words with what was heard."""
    expected = script_words(script)
    heard = set(_WORD.findall(str(transcript or "").lower()))
    missing = [word for word in dict.fromkeys(expected) if word not in heard]
    share = 1 - len(missing) / len(set(expected)) if expected else 1.0
    result = {
        "narration": "matches" if share >= MATCH_SHARE else "differs",
        "heard_share": round(share, 2),
        "missing": missing[:12],
    }
    if seconds is not None:
        result["seconds"] = round(seconds, 2)
        result["length_ok"] = CLIP_SECONDS[0] <= seconds <= CLIP_SECONDS[1]
    return result


def _audio_mp3(ffmpeg, clip, folder):
    target = Path(folder) / "audio.mp3"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1",
         "-ar", "16000", "-b:a", "48k", str(target)],
        check=True, capture_output=True, timeout=120,
    )
    return target.read_bytes()


def check_clip(record, clip):
    """Transcribe the clip and compare it with the script; None if it
    cannot be checked (no script, no sound, or Gemini unavailable)."""
    if not record.get("flow_story") or not script_words(record.get("video_script")):
        return None
    from media_renderer import ffmpeg_executable
    from video_renderer import clip_info

    seconds, has_sound = clip_info(clip)
    if not has_sound:
        return {"narration": "silent", "missing": [], "heard_share": 0.0,
                "seconds": round(seconds or 0, 2),
                "length_ok": bool(seconds) and CLIP_SECONDS[0] <= seconds <= CLIP_SECONDS[1]}
    try:
        with tempfile.TemporaryDirectory() as folder:
            audio = _audio_mp3(ffmpeg_executable(), clip, folder)
        transcript = transcribe_audio(base64.b64encode(audio).decode(), "audio/mpeg")
    except (AIServiceError, subprocess.SubprocessError, OSError):
        return None
    result = compare(record.get("video_script"), transcript, seconds)
    result["transcript"] = transcript.strip()
    return result
