"""Publish scheduled one-image Reels whose time has come.

Run it by hand, or install it as a macOS LaunchAgent that runs every
minute (and once after the Mac wakes):

    python3 -m scripts.publish_scheduled            # publish what is due now
    python3 -m scripts.publish_scheduled --install  # run automatically
    python3 -m scripts.publish_scheduled --uninstall
"""

import argparse
import fcntl
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app_settings import get_setting
from instagram_publisher import InstagramPublisher, InstagramPublishError
from project_paths import GENERATED_ASSETS_DIRECTORY, PROJECT_ROOT
from scripts.review_ui import publish_due_posts


LABEL = "com.dagnosticbeing.publish-scheduled"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = GENERATED_ASSETS_DIRECTORY / "scheduler.log"
LOCK_PATH = GENERATED_ASSETS_DIRECTORY / ".scheduler.lock"
INTERVAL_SECONDS = 60
ENV_PATH = PROJECT_ROOT / ".env"
TOKEN_STATE_PATH = GENERATED_ASSETS_DIRECTORY / ".token_refresh.json"
# Long-lived tokens last ~60 days; refreshing weekly keeps a wide margin.
TOKEN_REFRESH_EVERY = timedelta(days=7)
TOKEN_RETRY_AFTER = timedelta(days=1)
TOKEN_SETTING = "INSTAGRAM_ACCESS_TOKEN"


def replace_env_value(env_path, name, value):
    """Rewrite one NAME=value line in a .env file, keeping everything else."""
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name and not line.lstrip().startswith("#"):
            ending = "\n" if line.endswith("\n") else ""
            lines[index] = f"{name}={value}{ending}"
            replaced = True
            break
    if not replaced:
        raise ValueError(f"{name} is not set in {env_path.name}.")
    temporary = env_path.with_name(env_path.name + ".tmp")
    temporary.write_text("".join(lines), encoding="utf-8")
    os.chmod(temporary, env_path.stat().st_mode)
    os.replace(temporary, env_path)


def refresh_token_if_due(
    now=None,
    env_path=ENV_PATH,
    state_path=TOKEN_STATE_PATH,
    publisher_factory=InstagramPublisher,
):
    """Extend the Instagram token about weekly; return a log line or None."""
    if not get_setting(TOKEN_SETTING):
        return None
    now = now or datetime.now(timezone.utc)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    def older_than(key, age):
        value = state.get(key)
        return not value or now - datetime.fromisoformat(value) >= age

    if not (
        older_than("last_success", TOKEN_REFRESH_EVERY)
        and older_than("last_attempt", TOKEN_RETRY_AFTER)
    ):
        return None
    state["last_attempt"] = now.isoformat()
    try:
        token, expires_in = publisher_factory().refresh_access_token()
        replace_env_value(env_path, TOKEN_SETTING, token)
        os.environ[TOKEN_SETTING] = token
        state["last_success"] = now.isoformat()
        state.pop("last_error", None)
        days = int(expires_in) // 86400 if expires_in else None
        message = "token refreshed" + (f"; valid for ~{days} days" if days else "")
    except (InstagramPublishError, OSError, ValueError) as error:
        state["last_error"] = str(error)
        message = f"token refresh failed: {error}"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return message


def run_once():
    GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            # A slow Reel upload must not overlap with the next run.
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        stamp = datetime.now().isoformat(timespec="seconds")
        refreshed = refresh_token_if_due()
        if refreshed:
            print(f"{stamp} {refreshed}", flush=True)
        for content_id, outcome, detail in publish_due_posts():
            print(f"{stamp} {content_id} {outcome}: {detail or ''}", flush=True)
    return 0


def install():
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "scripts.publish_scheduled"],
        "WorkingDirectory": str(PROJECT_ROOT),
        "StartInterval": INTERVAL_SECONDS,
        "RunAtLoad": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }))
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    minutes = INTERVAL_SECONDS // 60
    every = "minute" if minutes == 1 else f"{minutes} minutes"
    print(f"Installed. Scheduled Reels are checked every {every}; log: {LOG_PATH}")
    return 0


def uninstall():
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
    print("Uninstalled the scheduled publisher.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="Run every minute.")
    group.add_argument("--uninstall", action="store_true", help="Stop running automatically.")
    args = parser.parse_args(argv)
    if args.install:
        return install()
    if args.uninstall:
        return uninstall()
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
