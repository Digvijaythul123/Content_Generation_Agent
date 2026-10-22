"""Print Instagram performance for published posts, grouped by choices.

    python3 -m scripts.performance_report
"""

import sys

from analytics import refresh_report
from instagram_publisher import InstagramPublishError


def main(argv=None):
    try:
        report = refresh_report()
    except InstagramPublishError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Fetched {report['fetched_at'][:16]} UTC\n")
    print(f"{'Post':10} {'Views':>6} {'Reach':>6} {'Saves':>6} {'Shares':>6} {'Watch s':>8}  Title")
    for row in report["posts"]:
        watch = row["avg_watch_seconds"] if row["avg_watch_seconds"] is not None else "-"
        print(f"{row['id']:10} {row['views']:>6} {row['reach']:>6} {row['saved']:>6} "
              f"{row['shares']:>6} {watch:>8}  {row['title'].replace('**', '')}")
    for label, items in report["groups"].items():
        print(f"\nBy {label.lower()}:")
        for item in items:
            watch = item["avg_watch_seconds"] if item["avg_watch_seconds"] is not None else "-"
            print(f"  {item['value']:24} posts {item['posts']:>2} · avg views "
                  f"{item['avg_views']:>5} · saves {item['saves']:>3} · shares "
                  f"{item['shares']:>3} · watch {watch}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
