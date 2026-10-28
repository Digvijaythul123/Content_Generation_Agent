import argparse
from pathlib import Path

from config_loader import (
    ConfigurationError,
    load_brand,
    load_profile_engagement,
    load_comedy_config,
    load_profile_subtypes,
    load_focus_thinkers,
)
from content_agent import apply_hook_options
from content_models import send_line, split_first_comment
from content_pipeline import generate_content
from post_prompt import build_post_prompt_file
from project_paths import GENERATED_ASSETS_DIRECTORY
from post_storage import create_post
from reel_storage import create_reel


def _art_style(brand):
    return brand.template.art_style if brand is not None else None


def _save_result(result, caption_language="english"):
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
    if result.request.subtype:
        data["subtype"] = result.request.subtype
    if result.request.thinker_id:
        data["thinker_id"] = result.request.thinker_id
    if result.request.visual_style:
        data["visual_style"] = result.request.visual_style
    if result.request.life_scene:
        data["life_scene"] = result.request.life_scene
    if result.request.scenery:
        data["scenery"] = result.request.scenery
    if result.request.weather:
        data["weather"] = result.request.weather
    if data.get("caption"):
        # A quiz answer goes in the first comment, not the caption.
        data["caption"], first_comment = split_first_comment(
            data["caption"], hide_source=data.get("subtype") == "real_or_fake"
        )
        if first_comment:
            data["first_comment"] = first_comment
    if caption_language != "english":
        data["caption_language"] = caption_language
    if result.request.content_format.id == "carousel":
        # The cover art keeps its upper part open, like a poster.
        data["layout"] = "poster"
    if result.request.content_format.id == "image_reel":
        data["layout"] = "poster"
        data["share_to_youtube"] = True  # also a YouTube Short
        try:
            default_cta = load_profile_engagement(data["profile_id"]).get("default_cta")
        except ConfigurationError:
            default_cta = None
        # The caption's "Send this to the friend who ..." line names a person,
        # which gets more sends than a general line; use it for the end card.
        targeted = send_line(data.get("caption"))
        if targeted or default_cta:
            data["cta"] = targeted or default_cta
    apply_hook_options(data)

    if result.request.content_format.content_kind == "post":
        post_id, file_path = create_post(data)
        if "design_prompt" in result.content.fields:
            prompt_file = (
                GENERATED_ASSETS_DIRECTORY / f"{post_id}_design_prompt.txt"
            )
            GENERATED_ASSETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(
                build_post_prompt_file(
                    data,
                    result.request.content_format,
                    result.request.platform,
                    result.request.category_id,
                    _art_style(result.request.brand),
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
        help=(
            "Optional subtype for the selected profile (Comedy subtype, QA "
            "topic pillar, or Rational Thoughts story mode)."
        ),
    )
    parser.add_argument(
        "--thinker",
        default=None,
        help=(
            "Optional thinker ID from the profile's thinker library, such as "
            "buddha; omit to let the model choose (batches rotate thinkers)."
        ),
    )
    parser.add_argument(
        "--visual-style",
        default=None,
        help=(
            "Optional art style for post formats, such as cinematic_photo, "
            "living_thinker, thinker_statue, 3d_render, conceptual_metaphor, "
            "storybook_monk, ink_wash, or painterly (default: the story "
            "mode's style)."
        ),
    )
    parser.add_argument(
        "--scenery",
        default="auto",
        help=(
            "Place for the art, such as desert_dunes, tropical_beach, "
            "cave_temple, or alpine_lake; 'auto' (default) rotates places, "
            "'none' keeps the story's own setting."
        ),
    )
    parser.add_argument(
        "--weather",
        default="auto",
        help=(
            "Weather and light for the art, such as overcast, monsoon_rain, "
            "misty_morning, or moonlit_night; 'auto' (default) rotates, "
            "'none' leaves it to the story."
        ),
    )
    parser.add_argument(
        "--caption-language",
        choices=("english", "hinglish", "hindi", "thai", "sinhala", "vietnamese",
                 "burmese", "japanese", "chinese"),
        default="english",
        help="Add one short line in another language to the caption (on-screen copy stays English).",
    )
    parser.add_argument(
        "--hashtags",
        type=int,
        choices=range(0, 6),
        default=None,
        help="How many hashtags (0-5; default 5). Compare reach by count in Performance.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help=(
            "Generate this many separate drafts (1-10; batches rotate "
            "subtypes and thinkers when none is selected)."
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
    profile_id = args.profile
    if profile_id is None and args.category is None and args.brand != "":
        profile_id = load_brand(args.brand or "default").default_profile_id
    qa_subtypes = ()
    thinker_ids = ()
    if profile_id not in (None, "comedy") and args.count > 1:
        if args.qa_subtype is None and args.subtype is None:
            qa_subtypes = tuple(
                subtype["id"] for subtype in load_profile_subtypes(profile_id)
            )
        if args.thinker is None:
            thinker_ids = tuple(
                thinker["id"] for thinker in load_focus_thinkers(profile_id)
            )
    for index in range(args.count):
        comedy_subtype = args.comedy_subtype
        if comedy_subtypes:
            comedy_subtype = comedy_subtypes[index % len(comedy_subtypes)]
        subtype_id = args.qa_subtype
        if args.subtype:
            if args.profile == "comedy":
                comedy_subtype = args.subtype
            elif profile_id is not None:
                subtype_id = args.subtype
            else:
                parser.error("--subtype requires a content profile.")
        if qa_subtypes:
            subtype_id = qa_subtypes[index % len(qa_subtypes)]
        thinker_id = args.thinker
        if thinker_ids:
            thinker_id = thinker_ids[index % len(thinker_ids)]
        result = generate_content(
            profile_id=args.profile,
            brand_id=args.brand,
            format_id=args.format,
            platform_id=args.platform,
            brief=brief,
            category_id=args.category,
            comedy_subtype=comedy_subtype,
            subtype=subtype_id,
            thinker_id=thinker_id,
            visual_style=args.visual_style,
            caption_language=args.caption_language,
            scenery=args.scenery,
            weather=args.weather,
            hashtag_count=args.hashtags,
        )
        _save_result(result, args.caption_language)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())