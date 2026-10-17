import sys

from reel_storage import ReelStorageError
from scripts.review_ui import ReviewUIError, review_content


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m scripts.approve_reel <reel_id>")
        return 1

    reel_id = sys.argv[1]
    try:
        review_content("reel", reel_id, "Approved")
    except FileNotFoundError:
        print(f"Reel not found: {reel_id}")
        return 1
    except (ReelStorageError, ReviewUIError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"{reel_id} approved successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
