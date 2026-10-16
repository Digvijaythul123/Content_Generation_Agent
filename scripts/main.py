import argparse
from pathlib import Path

from content_pipeline import generate_content
from post_prompt import build_ready_design_prompt
from project_paths import GENERATED_ASSETS_DIRECTORY
from post_storage import create_post
from reel_storage import create_reel


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a configured social content draft."
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Content profile to use (brand default: rational_thoughts).",
    )
    parser.add_argument(
        "--brand",
        default=None,
        help="Brand configuration to use (default: default).",
    )
    parser.add_argument(
        "--format",
        default=None,
        help="Content format (defaults to the selected brand's default).",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Platform (defaults to the selected brand's default).",
    )
    brief_source = parser.add_mutually_exclusive_group()
    brief_source.add_argument(
        "--brief",
        help="A short generation brief to guide the content.",
    )
    brief_source.add_argument(
        "--brief-file",
        type=Path,
        help="Read the generation brief from a UTF-8 text file.",
    )
    args = parser.parse_args(argv)

    try:
        brief = (
            args.brief_file.read_text(encoding="utf-8")
            if args.brief_file
            else args.brief
        )
    except (OSError, UnicodeError) as error:
        parser.error(f"Could not read brief file {args.brief_file}: {error}")
    if brief is not None and not brief.strip():
        parser.error("The generation brief must not be empty.")
    if brief is not None:
        brief = brief.strip()

    print("Instagram Manager Agent Started\n")

    result = generate_content(
        profile_id=args.profile,
        brand_id=args.brand,
        format_id=args.format,
        platform_id=args.platform,
        brief=brief,
    )

    print(result.content.raw_content)

    data = {
        "brand_id": result.request.brand.id,
        "profile_id": result.request.profile.id,
        "format_id": result.request.content_format.id,
        "platform_id": result.request.platform.id,
        "brief": result.request.brief,
        **result.content.to_legacy_mapping(),
        "status": "Draft",
    }

    if result.request.content_format.content_kind == "post":
        post_id, file_path = create_post(data)
        prompt_file = (
            GENERATED_ASSETS_DIRECTORY / f"{post_id}_design_prompt.txt"
        )
        GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(
            build_ready_design_prompt(
                result.content.fields,
                result.request.content_format,
                result.request.platform,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nPost saved to {file_path}")
        print(f"Design prompt saved to {prompt_file}")
    else:
        _, file_path = create_reel(data)
        print(f"\nContent saved to {file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())