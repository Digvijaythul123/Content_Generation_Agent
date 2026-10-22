"""Back up local content (drafts, art, renders, history, music) to iCloud Drive.

These folders are ignored by git, so this is their only copy elsewhere.
Secrets in .env are deliberately not included.

    python3 -m scripts.backup_content            # back up now
    python3 -m scripts.backup_content --dest DIR # back up to another folder
"""

import argparse
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT


CONTENT_FOLDERS = (
    "generated_posts",
    "generated_assets",
    "generated_reels",
    "generated_videos",
    "generated_images",
    "creative_assets",
    "music",
)
ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
DEFAULT_DESTINATION = ICLOUD_DRIVE / "Content_Generation_Agent backups"
KEEP_BACKUPS = 4
BACKUP_STATE_PATH = GENERATED_ASSETS_DIRECTORY / ".backup_state.json"
BACKUP_EVERY = timedelta(days=7)
# Lock files and caches are not worth keeping.
_SKIP_NAMES = {".scheduler.lock", ".DS_Store"}


def default_destination():
    if ICLOUD_DRIVE.is_dir():
        return DEFAULT_DESTINATION
    return Path.home() / "Documents" / "Content_Generation_Agent backups"


def create_backup(destination=None, root=PROJECT_ROOT, keep=KEEP_BACKUPS, now=None):
    """Write a dated zip of the content folders and prune older backups."""
    destination = Path(destination or default_destination())
    destination.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M")
    final = destination / f"content_{stamp}.zip"
    partial = final.with_suffix(".zip.partial")
    files = 0
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in CONTENT_FOLDERS:
            base = root / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.name not in _SKIP_NAMES:
                    archive.write(path, path.relative_to(root))
                    files += 1
    partial.replace(final)
    backups = sorted(destination.glob("content_*.zip"))
    for old in backups[:-keep] if keep else []:
        old.unlink()
    return final, files


def backup_if_due(now=None, state_path=BACKUP_STATE_PATH, **kwargs):
    """Back up about weekly; return a log line, or None when not due."""
    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(json.loads(state_path.read_text())["last"])
    except (OSError, ValueError, KeyError):
        last = None
    if last and now - last < BACKUP_EVERY:
        return None
    try:
        path, files = create_backup(**kwargs)
    except OSError as error:
        return f"backup failed: {error}"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last": now.isoformat(), "path": str(path)}))
    return f"backup saved: {path.name} ({files} files)"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", help="Folder for the backup (default: iCloud Drive).")
    args = parser.parse_args(argv)
    path, files = create_backup(args.dest)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Backed up {files} files ({size_mb:.1f} MB) to {path}")
    print("Note: .env (tokens and keys) is not included; keep it safe separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
