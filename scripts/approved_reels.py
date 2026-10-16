import sys

from reel_storage import ReelStorageError, list_reel_paths, load_reel


def main():
    for file_path in list_reel_paths():
        try:
            reel = load_reel(file_path.stem)
        except (FileNotFoundError, ReelStorageError) as error:
            print(error, file=sys.stderr)
            return 1

        if reel.get("status") == "Approved":
            print(
                f"{reel.get('id', 'NO_ID')} | "
                f"{reel.get('title', 'NO_TITLE')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())