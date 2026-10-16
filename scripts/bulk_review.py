import sys

from reel_storage import ReelStorageError, list_reel_paths, load_reel, save_reel


def main():
    for file_path in list_reel_paths():
        reel_id = file_path.stem
        try:
            reel = load_reel(reel_id)
        except (FileNotFoundError, ReelStorageError) as error:
            print(error, file=sys.stderr)
            return 1

        print("\n" + "=" * 80)
        print(f"ID: {reel.get('id', 'NO_ID')}")
        print(f"Status: {reel.get('status', 'UNKNOWN')}")
        print(f"Title: {reel.get('title', 'NO_TITLE')}")
        print(f"Hook: {reel.get('hook', '')}")

        choice = input("\n[A]pprove / [R]eject / [S]kip ? ").strip().lower()

        if choice == "a":
            reel["status"] = "Approved"
        elif choice == "r":
            reel["status"] = "Rejected"
        elif choice == "s":
            continue

        try:
            save_reel(reel_id, reel)
        except ReelStorageError as error:
            print(error, file=sys.stderr)
            return 1

        print("Updated.")

    return 0


if __name__ == "__main__":
    sys.exit(main())