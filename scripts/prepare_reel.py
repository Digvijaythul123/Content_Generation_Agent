import argparse
import sys

from ai_service import AIServiceError
from config_loader import ConfigurationError
from reel_storage import ReelStorageError, validate_reel_id
from scripts.image_prompt_generator import generate_image_prompts
from scripts.storyboard_generator import (
    StoryboardValidationError,
    generate_storyboard,
)
from scripts.video_prompt_generator import generate_master_prompt


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prepare scene, image, and master video prompts for a reel."
    )
    parser.add_argument("reel_id", help="Saved reel ID, such as reel_016.")
    args = parser.parse_args(argv)

    try:
        validate_reel_id(args.reel_id)
        storyboard_file = generate_storyboard(args.reel_id)
        print(f"Storyboard saved to {storyboard_file}")
        image_prompts_file = generate_image_prompts(args.reel_id)
        print(f"Image prompts saved to {image_prompts_file}")
        video_prompt_file = generate_master_prompt(args.reel_id)
        print(f"Master video prompt saved to {video_prompt_file}")
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    except (
        AIServiceError,
        ConfigurationError,
        ReelStorageError,
        StoryboardValidationError,
    ) as error:
        print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
