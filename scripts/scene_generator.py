import sys

from project_paths import GENERATED_VIDEOS_DIRECTORY
from reel_storage import ReelStorageError, validate_reel_id
from scripts.storyboard_generator import (
    StoryboardValidationError,
    generate_storyboard,
)


def generate_scenes(reel_id):
    validate_reel_id(reel_id)
    generate_storyboard(reel_id)
    return GENERATED_VIDEOS_DIRECTORY / f"{reel_id}_scenes.txt"


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m scripts.scene_generator <reel_id>")
        return 1

    reel_id = sys.argv[1]
    try:
        output_file = generate_scenes(reel_id)
    except FileNotFoundError:
        print(f"Reel not found: {reel_id}")
        return 1
    except (ReelStorageError, StoryboardValidationError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Scenes saved to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
