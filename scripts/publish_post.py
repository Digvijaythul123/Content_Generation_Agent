import argparse
import sys

from art_generator import ArtGenerationError
from content_models import ContentValidationError
from facebook_publisher import FacebookPublishError, FacebookPublisher, facebook_configured
from instagram_publisher import InstagramPublishError, InstagramPublisher
from media_host import MediaHostError
from media_renderer import MediaRenderError, post_image_path
from post_storage import PostStorageError, load_post
from video_renderer import reel_video_path
from scripts.review_ui import (
    ReviewUIError,
    get_art_prompt,
    get_pipeline,
    publish_content,
    run_production_stage,
    upload_artwork,
)


_ERRORS = (
    ArtGenerationError,
    ContentValidationError,
    InstagramPublishError,
    FacebookPublishError,
    MediaHostError,
    MediaRenderError,
    PostStorageError,
    ReviewUIError,
    OSError,
    ValueError,
)


def _render_outputs(post_id):
    """Render the image, plus the MP4 when the post is a one-image Reel."""
    run_production_stage("post", post_id, "instagram_image")
    print(f"Rendered {post_image_path(post_id)}")
    stages = {stage["id"] for stage in get_pipeline("post", post_id)["stages"]}
    if "reel_video" in stages:
        print("Rendering the Reel video…")
        run_production_stage("post", post_id, "reel_video")
        print(f"Rendered {reel_video_path(post_id)}")
        print("Upload the MP4 in the Instagram app and add music there.")
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Render an approved Instagram Feed post and publish it. "
            "Review the rendered image before publishing."
        )
    )
    parser.add_argument("post_id", nargs="?", help="Post ID, for example post_008.")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render the image for review and stop.",
    )
    parser.add_argument(
        "--new-art",
        action="store_true",
        help="Paint new background artwork (paid Gemini call) and re-render.",
    )
    parser.add_argument(
        "--art-prompt",
        action="store_true",
        help="Print the art prompt to paste into the Gemini or ChatGPT app.",
    )
    parser.add_argument(
        "--art-file",
        metavar="PATH",
        help="Use an image you made yourself as the artwork, then re-render.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Upload the image and print its public URL without posting.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Publish without the interactive confirmation prompt.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the Instagram connection and quota without posting.",
    )
    parser.add_argument(
        "--refresh-token",
        action="store_true",
        help="Extend the long-lived Instagram token and print the new value.",
    )
    args = parser.parse_args(argv)

    try:
        if args.check:
            publisher = InstagramPublisher()
            account = publisher.account_info()
            used, total = publisher.publishing_quota()
            print(
                f"Connected to @{account.get('username')} "
                f"({account.get('account_type', 'unknown type')}, "
                f"ID {account.get('user_id') or account.get('id')})."
            )
            print(f"Posts published via API in the last 24h: {used}/{total}.")
            if facebook_configured():
                page = FacebookPublisher().page_info()
                print(f"Facebook Page connected: {page.get('name')} (ID {page.get('id')}).")
            else:
                print("Facebook Page: not set up (FACEBOOK_PAGE_ID / FACEBOOK_PAGE_TOKEN in .env).")
            return 0
        if args.refresh_token:
            token, expires_in = InstagramPublisher().refresh_access_token()
            print("New INSTAGRAM_ACCESS_TOKEN (update your .env):")
            print(token)
            if expires_in:
                print(f"Expires in about {int(expires_in) // 86400} days.")
            return 0
        if not args.post_id:
            parser.error("post_id is required unless --check or --refresh-token is used.")

        if args.art_prompt:
            print(get_art_prompt("post", args.post_id))
            return 0
        if args.art_file:
            with open(args.art_file, "rb") as art_file:
                upload_artwork("post", args.post_id, art_file.read())
            print(f"Using {args.art_file} as the artwork.")
            _render_outputs(args.post_id)
            return 0

        image_path = post_image_path(args.post_id)
        is_image_reel = load_post(args.post_id).get("format_id") == "image_reel"
        if (
            args.new_art
            or args.render_only
            or is_image_reel
            or not image_path.is_file()
        ):
            stages = {
                stage["id"]: stage
                for stage in get_pipeline("post", args.post_id)["stages"]
            }
            artwork = stages.get("artwork")
            if artwork and (args.new_art or artwork["status"] != "ready"):
                print("Painting background artwork with Gemini…")
                run_production_stage("post", args.post_id, "artwork")
            if _render_outputs(args.post_id):
                return 0
            if not args.render_only:
                print("Review the image, then run this command again to publish.")
            return 0

        record = load_post(args.post_id)
        if not args.dry_run and not args.yes:
            print(f"Image:   {image_path}")
            print(f"Caption:\n{record.get('caption', '')}\n")
            answer = input("Publish this post to Instagram now? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Not published.")
                return 1

        result = publish_content("post", args.post_id, dry_run=args.dry_run)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    except _ERRORS as error:
        print(error, file=sys.stderr)
        return 1

    if result["dry_run"]:
        print(f"Dry run: uploaded to {result['media_url']} (not posted).")
    else:
        print(f"Published {args.post_id}: {result.get('permalink') or result['media_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
