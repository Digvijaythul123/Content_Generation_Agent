import argparse
from pathlib import Path

from config_loader import load_comedy_config, load_profile_subtypes
from content_pipeline import generate_content
from post_prompt import build_ready_design_prompt
from project_paths import GENERATED_ASSETS_DIRECTORY
from post_storage import create_post
from reel_storage import create_reel


def _save_result(result):
    print(result.content.raw_content)
    data = {
        "brand_id": (
            result.request.brand.id if result.request.brand is not None else None
        ),
        "profile_id": result.request.profile.id,
        "format_id": result.request.content_format.id,
        "platform_id": result.request.platform.id,
        "brief": result.request.brief,
        **result.content.to_legacy_mapping(),
        "status": "Draft",
    }
    if result.request.category_id:
        data["category_id"] = result.request.category_id
        if result.request.comedy_subtype:
            data["comedy_subtype"] = result.request.comedy_subtype
    if result.request.qa_subtype:
        data["qa_subtype"] = result.request.qa_subtype

    if result.request.content_format.content_kind == "post":
        post_id, file_path = create_post(data)
        if "design_prompt" in result.content.fields:
            prompt_file = (
                GENERATED_ASSETS_DIRECTORY / f"{post_id}_design_prompt.txt"
            )
            GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(
                build_ready_design_prompt(
                    result.content.fields,
                    result.request.content_format,
                    result.request.platform,
                    result.request.category_id,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"Design prompt saved to {prompt_file}")
        print(f"\nPost saved to {file_path}")
    else:
        _, file_path = create_reel(data)
        print(f"\nContent saved to {file_path}")


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
    parser.add_argument(
        "--category",
        default=None,
        help="Optional content category, currently: comedy.",
    )
    parser.add_argument(
        "--comedy-subtype",
        default=None,
        help="Optional Comedy subtype ID; omit to let the model select one.",
    )
    parser.add_argument(
        "--qa-subtype",
        default=None,
        help="Optional QA topic-pillar ID (legacy alias for --subtype).",
    )
    parser.add_argument(
        "--subtype",
        default=None,
        help="Optional subtype for the selected Comedy or QA profile.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help=(
            "Generate this many separate drafts (1-10; Comedy and QA batches "
            "rotate subtypes/topic pillars when none is selected)."
        ),
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
    if args.subtype and (args.qa_subtype or args.comedy_subtype):
        parser.error("Use --subtype or a legacy subtype option, not both.")
    if not 1 <= args.count <= 10:
        parser.error("--count must be between 1 and 10.")

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

    comedy_subtypes = ()
    if (
        args.category == "comedy"
        and args.comedy_subtype is None
        and args.subtype is None
        and args.count > 1
    ):
        comedy_subtypes = tuple(
            subtype["id"] for subtype in load_comedy_config()["subtypes"]
        )
    qa_subtypes = ()
    if (
        args.profile == "qa_engineering_ai"
        and args.qa_subtype is None
        and args.subtype is None
        and args.count > 1
    ):
        qa_subtypes = tuple(
            subtype["id"]
            for subtype in load_profile_subtypes("qa_engineering_ai")
        )
    for index in range(args.count):
        comedy_subtype = args.comedy_subtype
        if comedy_subtypes:
            comedy_subtype = comedy_subtypes[index % len(comedy_subtypes)]
        qa_subtype = args.qa_subtype
        if args.subtype:
            if args.profile == "comedy":
                comedy_subtype = args.subtype
            elif args.profile == "qa_engineering_ai":
                qa_subtype = args.subtype
            else:
                parser.error(
                    "--subtype requires --profile comedy or "
                    "--profile qa_engineering_ai."
                )
        if qa_subtypes:
            qa_subtype = qa_subtypes[index % len(qa_subtypes)]
        result = generate_content(
            profile_id=args.profile,
            brand_id=args.brand,
            format_id=args.format,
            platform_id=args.platform,
            brief=brief,
            category_id=args.category,
            comedy_subtype=comedy_subtype,
            qa_subtype=qa_subtype,
        )
        _save_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())