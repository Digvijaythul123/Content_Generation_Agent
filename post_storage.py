import json
import os
from pathlib import Path
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
