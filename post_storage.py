import json
import os
from pathlib import Path
import re
import tempfile

from project_paths import GENERATED_POSTS_DIRECTORY


class PostStorageError(ValueError):
    """Raised when a single-page post cannot be safely saved."""


def create_post(record):
    if not isinstance(record, dict):
        raise PostStorageError("Post record must be a dictionary.")

    GENERATED_POSTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        post_id = f"post_{number:03d}"
        path = GENERATED_POSTS_DIRECTORY / f"{post_id}.json"
        if path.exists():
            number += 1
            continue

        record_to_save = dict(record)
        record_to_save["id"] = post_id
        temporary_path = _write_temporary_json(path, record_to_save)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            number += 1
            continue
        except OSError as error:
            raise PostStorageError(
                f"Could not create post record {path}: {error}"
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)
        return post_id, path


def post_path(post_id):
    if not isinstance(post_id, str) or not re.fullmatch(
        r"post_[A-Za-z0-9_-]+", post_id
    ):
        raise PostStorageError(f"Invalid post ID: {post_id!r}")
    return GENERATED_POSTS_DIRECTORY / f"{post_id}.json"


def load_post(post_id):
    path = post_path(post_id)
    if not path.is_file():
        raise FileNotFoundError(f"Post not found: {post_id}")
    try:
        with path.open(encoding="utf-8") as post_file:
            record = json.load(post_file)
    except (OSError, json.JSONDecodeError) as error:
        raise PostStorageError(
            f"Could not read post record {path}: {error}"
        ) from error
    if not isinstance(record, dict):
        raise PostStorageError(f"Post record {path} must contain a JSON object.")
    return record


def save_post(post_id, record):
    path = post_path(post_id)
    if not isinstance(record, dict):
        raise PostStorageError("Post record must be a dictionary.")
    _atomic_write_json(path, record)
    return path


def _atomic_write_json(destination, record):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _write_temporary_json(destination, record)
    try:
        os.replace(temporary_path, destination)
    except OSError as error:
        raise PostStorageError(
            f"Could not safely write post record {destination}: {error}"
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
            json.dump(record, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except (OSError, TypeError, ValueError) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise PostStorageError(
            f"Could not prepare post record {destination}: {error}"
        ) from error
