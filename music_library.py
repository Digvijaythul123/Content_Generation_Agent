"""Royalty-free background music for rendered Reels.

Drop licensed tracks (for example from Pixabay Music or the YouTube Audio
Library) into the ``music/`` folder. Name each file after its mood, such as
``slow_reflective_flute.mp3`` or ``tense_dark_drone.mp3``: the picker matches
those words against the post's music cue.
"""

import hashlib
import re

from project_paths import PROJECT_ROOT


MUSIC_DIRECTORY = PROJECT_ROOT / "music"
MUSIC_SUFFIXES = (".mp3", ".m4a", ".aac", ".wav")
# Stored in a post's ``music_track`` to render it without audio.
SILENT = "none"
_WORD = re.compile(r"[a-z]+")
_STOP_WORDS = {"a", "an", "and", "the", "with", "of", "to", "in", "on", "soft", "music"}


class MusicError(ValueError):
    """Raised when a requested music track is not available."""


def list_tracks():
    if not MUSIC_DIRECTORY.is_dir():
        return []
    return sorted(
        path
        for path in MUSIC_DIRECTORY.iterdir()
        if path.is_file()
        and path.suffix.lower() in MUSIC_SUFFIXES
        and not path.name.startswith(".")
    )


def _words(text):
    return {word for word in _WORD.findall(text.lower()) if word not in _STOP_WORDS}


def pick_track(record):
    """Return the track for a post, or None to render without music.

    A post's explicit ``music_track`` wins; otherwise the track whose file
    name shares the most words with the post's ``music_cue`` is chosen, and
    ties are broken by the post ID so each post keeps a stable choice.
    """
    choice = record.get("music_track")
    tracks = list_tracks()
    if choice == SILENT:
        return None
    if choice:
        for track in tracks:
            if track.name == choice:
                return track
        raise MusicError(f"Music track {choice!r} is not in the music folder.")
    if not tracks:
        return None
    cue = _words(str(record.get("music_cue") or ""))
    seed = str(record.get("id") or "")

    def score(track):
        overlap = len(cue & _words(track.stem.replace("_", " ").replace("-", " ")))
        tie_break = hashlib.sha256((seed + track.name).encode()).hexdigest()
        return (overlap, tie_break)

    return max(tracks, key=score)
