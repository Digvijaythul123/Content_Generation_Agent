import json
import os
from pathlib import Path
import re
import tempfile

from project_paths import GENERATED_REELS_DIRECTORY


_REEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_REEL_FILENAME_PATTERN = re.compile(r"^reel_(\d+)\.json$")


class ReelStorageError(ValueError):
    """Raised when a reel record cannot be safely read or written."""


def reel_path(reel_id):
    validate_reel_id(reel_id)
    return GENERATED_REELS_DIRECTORY / f"{reel_id}.json"


def validate_reel_id(reel_id):
    if not isinstance(reel_id, str) or not _REEL_ID_PATTERN.fullmatch(reel_id):
        raise ReelStorageError(f"Invalid reel ID: {reel_id!r}")


def list_reel_paths():
    if not GENERATED_REELS_DIRECTORY.exists():
        return []
    return sorted(GENERATED_REELS_DIRECTORY.glob("*.json"))


def load_reel(reel_id):
    path = reel_path(reel_id)
    if not path.is_file():
        raise FileNotFoundError(f"Reel not found: {reel_id}")
    try:
        with path.open(encoding="utf-8") as reel_file:
            record = json.load(reel_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ReelStorageError(
            f"Could not read reel record {path}: {error}"
        ) from error
    if not isinstance(record, dict):
        raise ReelStorageError(f"Reel record {path} must contain a JSON object.")
    return record


def save_reel(reel_id, record):
    path = reel_path(reel_id)
    if not isinstance(record, dict):
        raise ReelStorageError("Reel record must be a dictionary.")
    _atomic_write_json(path, record)
    return path


def create_reel(record):
    if not isinstance(record, dict):
        raise ReelStorageError("Reel record must be a dictionary.")

    GENERATED_REELS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        reel_id = f"reel_{number:03d}"
        path = reel_path(reel_id)
        if path.exists():
            number += 1
            continue

        record_to_save = dict(record)
        record_to_save["id"] = reel_id
        temporary_path = _write_temporary_json(path, record_to_save)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            number += 1
            continue
        except OSError as error:
            raise ReelStorageError(
                f"Could not create reel record {path}: {error}"
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)
        return reel_id, path


def _atomic_write_json(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _write_temporary_json(path, record)
    try:
        os.replace(temporary_path, path)
    except OSError as error:
        raise ReelStorageError(
            f"Could not safely write reel record {path}: {error}"
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_temporary_json(destination: Path, record):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(record, temporary_file, indent=4)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except (OSError, TypeError, ValueError) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ReelStorageError(
            f"Could not prepare reel record {destination}: {error}"
        ) from error
