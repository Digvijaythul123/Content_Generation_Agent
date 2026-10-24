"""Set up and check the cloud scheduler (the Cloudflare Worker).

    python3 -m scripts.cloud_scheduler --setup          # send tokens from .env, check health
    python3 -m scripts.cloud_scheduler --status         # health and queued posts
    python3 -m scripts.cloud_scheduler --test post_031  # dry run: Instagram accepts the
                                                        # media, nothing is published
"""

import argparse
import sys
from datetime import datetime, timezone

from app_settings import current_file_setting, get_setting
from cloud_scheduler import CloudScheduler, CloudSchedulerError
from media_host import MediaHostError
from scripts.review_ui import queue_cloud_job, sync_cloud_jobs


TOKEN_SETTINGS = {
    "instagram_token": "INSTAGRAM_ACCESS_TOKEN",
    "instagram_account_id": "INSTAGRAM_ACCOUNT_ID",
    "facebook_page_id": "FACEBOOK_PAGE_ID",
    "facebook_page_token": "FACEBOOK_PAGE_TOKEN",
    "threads_user_id": "THREADS_USER_ID",
    "threads_token": "THREADS_ACCESS_TOKEN",
}


def _tokens():
    values = {}
    for field, setting in TOKEN_SETTINGS.items():
        value = current_file_setting(setting, get_setting(setting))
        if value:
            values[field] = value
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setup", action="store_true", help="Send tokens from .env and check the Worker.")
    parser.add_argument("--status", action="store_true", help="Show the Worker's health.")
    parser.add_argument("--test", metavar="POST_ID", help="Dry-run one approved post through the Worker.")
    args = parser.parse_args(argv)
    try:
        cloud = CloudScheduler()
        if args.setup:
            tokens = _tokens()
            cloud.put_tokens(tokens)
            print("Sent to the cloud scheduler: " + ", ".join(sorted(tokens)) + " (values not shown).")
        if args.setup or args.status:
            health = cloud.health()
            print(f"Cloud scheduler is up. Queued jobs: {health['queued']}. "
                  f"Tokens: {', '.join(name for name, ok in health['tokens'].items() if ok) or 'none'}.")
            if health.get("refresh_error"):
                print(f"Last token refresh failed: {health['refresh_error']}")
        if args.test:
            from post_storage import load_post
            if load_post(args.test).get("scheduled_at"):
                raise ValueError(f"{args.test} is scheduled; test with an approved post that is not.")
            now = datetime.now(timezone.utc).isoformat()
            queue_cloud_job(args.test, dry_run=True, due=now)
            print(f"Queued a dry run for {args.test}; asking the Worker to run now…")
            print(cloud.run_now())
            print("Collected:", sync_cloud_jobs() or "still processing (run --status or wait a minute)")
    except (CloudSchedulerError, MediaHostError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
