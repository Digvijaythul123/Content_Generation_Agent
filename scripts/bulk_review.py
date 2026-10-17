import sys

from reel_storage import ReelStorageError, list_reel_paths, load_reel
from scripts.review_ui import ReviewUIError, review_content


_DECISIONS = {"a": "Approved", "r": "Rejected"}


def main():
    for file_path in list_reel_paths():
        reel_id = file_path.stem
        try:
            reel = load_reel(reel_id)
        except (FileNotFoundError, ReelStorageError) as error:
            print(error, file=sys.stderr)
            return 1
        if reel.get("status", "Draft") != "Draft":
            continue

        print("\n" + "=" * 80)
        print(f"ID: {reel.get('id', 'NO_ID')}")
        print(f"Status: {reel.get('status', 'Draft')}")
        print(f"Title: {reel.get('title', 'NO_TITLE')}")
        print(f"Hook: {reel.get('hook', '')}")

        choice = input("\n[A]pprove / [R]eject / [S]kip ? ").strip().lower()
        if choice == "s":
            continue
        if choice not in _DECISIONS:
            print(f"Unrecognized choice {choice!r}; {reel_id} was not changed.")
            continue

        try:
            review_content("reel", reel_id, _DECISIONS[choice])
        except (ReelStorageError, ReviewUIError, ValueError) as error:
            print(error, file=sys.stderr)
            return 1

        print(f"{reel_id} marked {_DECISIONS[choice]}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
