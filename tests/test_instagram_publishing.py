import json
import re
from unittest.mock import Mock

import pytest
import requests

from content_models import (
    Brand,
    ContentValidationError,
    validate_instagram_caption,
)
from instagram_publisher import InstagramPublishError, InstagramPublisher
import media_renderer
from media_renderer import MediaRenderError, build_post_html
import post_storage
from scripts import review_ui
from scripts.storyboard_generator import build_storyboard


POST = {
    "id": "post_001",
    "brand_id": None,
    "profile_id": "rational_thoughts",
    "format_id": "single_page",
    "platform_id": "instagram_feed",
    "title": "Confidence <is> not evidence",
    "main_point": "Certainty is a feeling, not a fact.",
    "supporting_copy": "Ask what would change your mind.",
    "visual_labels": "Claim, Evidence",
    "caption": "Feeling sure is not the same as being right. #thinking",
    "status": "Approved",
}


def _response(payload, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    return response


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    posts = tmp_path / "posts"
    assets = tmp_path / "assets"
    posts.mkdir()
    monkeypatch.setattr(post_storage, "GENERATED_POSTS_DIRECTORY", posts)
    monkeypatch.setattr(media_renderer, "GENERATED_ASSETS_DIRECTORY", assets)
    monkeypatch.setattr(review_ui, "GENERATED_ASSETS_DIRECTORY", assets)
    monkeypatch.setitem(review_ui._CONTENT_DIRECTORIES, "post", posts)

    def write(record):
        (posts / f"{record['id']}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    def read(post_id="post_001"):
        return json.loads((posts / f"{post_id}.json").read_text(encoding="utf-8"))

    def render(post_id="post_001"):
        path = media_renderer.post_image_path(post_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8fake-jpeg")

    return Mock(write=write, read=read, render=render, assets=assets)


def test_instagram_caption_limits():
    assert validate_instagram_caption("  Hook line #one  ") == "Hook line #one"
    with pytest.raises(ContentValidationError, match="2200 characters"):
        validate_instagram_caption("x" * 2201)
    with pytest.raises(ContentValidationError, match="5 hashtags"):
        validate_instagram_caption(" ".join(f"#tag{n}" for n in range(31)))
    with pytest.raises(ContentValidationError, match="require a caption"):
        validate_instagram_caption("   ")


def test_post_html_escapes_copy_and_uses_brand_template():
    brand = Brand.from_mapping(
        {
            "id": "demo",
            "display_name": "Demo Brand",
            "default_profile_id": "comedy",
            "default_format_id": "reel",
            "default_platform_id": "instagram",
            "template": {"background": "#000000", "handle": "@demo"},
        }
    )
    html = build_post_html(POST, brand)
    assert "Confidence &lt;is&gt; not evidence" in html
    assert "<span>Claim</span><span>Evidence</span>" in html
    assert "background: #000000" in html
    assert "@demo" in html and "Demo Brand" in html


def test_post_html_requires_copy_and_skips_none_labels():
    html = build_post_html({**POST, "visual_labels": "None"})
    assert 'class="labels"' not in html
    with pytest.raises(MediaRenderError, match="main_point"):
        build_post_html({**POST, "main_point": " "})


def test_brand_template_rejects_unsafe_values():
    base = {
        "id": "demo",
        "display_name": "Demo",
        "default_profile_id": "comedy",
        "default_format_id": "reel",
        "default_platform_id": "instagram",
    }
    with pytest.raises(ContentValidationError, match="hex"):
        Brand.from_mapping({**base, "template": {"accent": "red"}})
    with pytest.raises(ContentValidationError, match="plain text"):
        Brand.from_mapping({**base, "template": {"font_family": "x;}</style>"}})


def _publisher(session, **kwargs):
    return InstagramPublisher(
        access_token="secret-token",
        account_id="123",
        base_url="https://graph.example/v1",
        session=session,
        sleep=lambda seconds: None,
        **kwargs,
    )


def test_publisher_creates_waits_and_publishes():
    session = Mock()
    session.get.side_effect = [
        _response({"data": [{"quota_usage": 2, "config": {"quota_total": 100}}]}),
        _response({"status_code": "IN_PROGRESS"}),
        _response({"status_code": "FINISHED"}),
        _response({"permalink": "https://instagram.com/p/abc", "is_ai_generated": True}),
    ]
    session.post.side_effect = [_response({"id": "c1"}), _response({"id": "m1"})]

    result = _publisher(session).publish_image("https://cdn/x.jpg", "Caption")

    assert result == {
        "media_id": "m1", "permalink": "https://instagram.com/p/abc", "ai_label": True
    }
    create, publish = session.post.call_args_list
    assert create.args[0] == "https://graph.example/v1/123/media"
    assert create.kwargs["data"]["image_url"] == "https://cdn/x.jpg"
    assert create.kwargs["data"]["is_ai_generated"] == "true"
    assert publish.kwargs["data"]["creation_id"] == "c1"


def test_publisher_stops_at_quota_and_processing_errors():
    session = Mock()
    session.get.return_value = _response(
        {"data": [{"quota_usage": 100, "config": {"quota_total": 100}}]}
    )
    with pytest.raises(InstagramPublishError, match="limit is reached"):
        _publisher(session).publish_image("https://cdn/x.jpg", "Caption")
    session.post.assert_not_called()

    session = Mock()
    session.get.return_value = _response({"status_code": "ERROR"})
    with pytest.raises(InstagramPublishError, match="status ERROR"):
        _publisher(session).wait_until_ready("c1")

    session.get.return_value = _response({"status_code": "IN_PROGRESS"})
    with pytest.raises(InstagramPublishError, match="still processing"):
        _publisher(session, poll_timeout_seconds=6).wait_until_ready("c1")


def test_publisher_reports_api_errors_without_leaking_token():
    session = Mock()
    session.post.return_value = _response(
        {"error": {"message": "Invalid image URL"}}, status=400
    )
    with pytest.raises(InstagramPublishError, match="HTTP 400: Invalid image URL"):
        _publisher(session).create_image_container("bad", "Caption")

    session.get.side_effect = requests.ConnectionError(
        "https://graph.example/?access_token=secret-token"
    )
    with pytest.raises(InstagramPublishError) as error:
        _publisher(session).publishing_quota()
    assert "secret-token" not in str(error.value)


def test_publish_requires_approval_and_rendered_image(workspace):
    workspace.write({**POST, "status": "Draft"})
    with pytest.raises(ValueError, match="Approved"):
        review_ui.publish_content("post", "post_001", host=Mock(), publisher=Mock())

    workspace.write(POST)
    with pytest.raises(ValueError, match="Render"):
        review_ui.publish_content("post", "post_001", host=Mock(), publisher=Mock())

    workspace.write({**POST, "platform_id": "linkedin"})
    workspace.render()
    with pytest.raises(ValueError, match="Instagram posts and Reels"):
        review_ui.publish_content("post", "post_001", host=Mock(), publisher=Mock())


def test_publish_uploads_publishes_and_records(workspace):
    workspace.write(POST)
    workspace.render()
    host = Mock()
    host.upload.return_value = ("key-1", "https://cdn/key-1.jpg")
    publisher = Mock()
    publisher.publish_image.return_value = {
        "media_id": "m1",
        "permalink": "https://instagram.com/p/abc",
    }

    result = review_ui.publish_content(
        "post", "post_001", host=host, publisher=publisher
    )

    assert result["permalink"] == "https://instagram.com/p/abc"
    publisher.publish_image.assert_called_once_with(
        "https://cdn/key-1.jpg", POST["caption"]
    )
    host.delete.assert_called_once_with("key-1")
    saved = workspace.read()
    assert saved["status"] == "Published"
    assert saved["instagram_media_id"] == "m1"
    assert "published_at" in saved
    stages = {stage["id"]: stage for stage in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["publishing"]["status"] == "ready"
    with pytest.raises(ValueError, match="unpublished"):
        review_ui.publish_content("post", "post_001", host=host, publisher=publisher)


def test_publish_dry_run_uploads_without_posting(workspace):
    workspace.write(POST)
    workspace.render()
    host = Mock()
    host.upload.return_value = ("key-1", "https://cdn/key-1.jpg")
    publisher = Mock()

    result = review_ui.publish_content(
        "post", "post_001", dry_run=True, host=host, publisher=publisher
    )

    assert result == {"dry_run": True, "media_url": "https://cdn/key-1.jpg"}
    publisher.publish_image.assert_not_called()
    assert workspace.read()["status"] == "Approved"


def test_failed_publish_is_recorded_and_retryable(workspace):
    workspace.write(POST)
    workspace.render()
    host = Mock()
    host.upload.return_value = ("key-1", "https://cdn/key-1.jpg")
    publisher = Mock()
    publisher.publish_image.side_effect = InstagramPublishError("boom")

    with pytest.raises(InstagramPublishError):
        review_ui.publish_content("post", "post_001", host=host, publisher=publisher)

    stages = {stage["id"]: stage for stage in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["publishing"]["status"] == "failed"
    assert stages["publishing"]["can_run"] is True
    assert workspace.read()["status"] == "Approved"


def test_storyboard_keeps_narrator_lines_as_narration():
    storyboard = build_storyboard(
        {
            "id": "reel_001",
            "title": "Hard work",
            "hook": "Stop bragging.",
            "script": (
                "(Visual: A clock ticking)\n"
                "Narrator: We treat the grind as a badge of honour.\n"
                "(Visual: A flat output line)\n"
                "NARRATION: Output is not a linear function of time."
            ),
            "caption": "Work smarter.",
        }
    ).to_mapping()
    scene = storyboard["scenes"][0]
    assert scene["visual_beats"] == ["A clock ticking", "A flat output line"]
    assert scene["narration"] == [
        "We treat the grind as a badge of honour.",
        "Output is not a linear function of time.",
    ]


import base64

import art_generator
from art_generator import ArtGenerationError, GeminiImageClient, build_art_prompt
from content_text import strip_highlights
from media_renderer import _copy_html


PAINTING_BRAND = {
    "id": "demo",
    "display_name": "Demo",
    "default_profile_id": "rational_thoughts",
    "default_format_id": "single_page",
    "default_platform_id": "instagram_feed",
    "template": {"layout": "quote_painting", "art_style": "Warm parchment"},
}


def test_highlight_markers_render_safely_and_strip():
    assert _copy_html("What you **don't keep**, <you> lose") == (
        'What you <span class="hl">don&#x27;t keep</span>, &lt;you&gt; lose'
    )
    assert strip_highlights("a **b** c**") == "a b c"


def test_quote_painting_layout_requires_and_embeds_artwork(tmp_path):
    brand = Brand.from_mapping(PAINTING_BRAND)
    with pytest.raises(MediaRenderError, match="artwork"):
        build_post_html(POST, brand)
    art = tmp_path / "art.png"
    art.write_bytes(b"png-bytes")
    html = build_post_html(POST, brand, art)
    assert "data:image/png;base64," + base64.b64encode(b"png-bytes").decode() in html
    assert "rgba(244, 239, 230, 0.88)" in html


def test_brand_template_rejects_unknown_layout():
    with pytest.raises(ContentValidationError, match="layout"):
        Brand.from_mapping({**PAINTING_BRAND, "template": {"layout": "collage"}})


def test_art_prompt_forbids_text_and_includes_style():
    prompt = build_art_prompt({"design_prompt": "A monk by a lake"}, "Warm parchment")
    assert "purely pictorial" in prompt and "A monk by a lake" in prompt
    assert not re.search(r"\btext\b|letters|caption", prompt, re.I)
    assert "Visual style: Warm parchment" in prompt
    with pytest.raises(ArtGenerationError, match="design prompt"):
        build_art_prompt({"design_prompt": " "})


def test_gemini_client_requests_4x5_image_and_decodes_it():
    session = Mock()
    session.post.return_value = _response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Here you go"},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(b"img").decode(),
                                }
                            },
                        ]
                    }
                }
            ]
        }
    )
    client = GeminiImageClient(api_key="k", model="m", session=session)

    assert client.generate("prompt") == (b"img", "image/png")
    call = session.post.call_args
    assert call.args[0].endswith("/models/m:generateContent")
    assert call.kwargs["headers"] == {"x-goog-api-key": "k"}
    assert call.kwargs["json"]["generationConfig"] == {
        "responseModalities": ["IMAGE"],
        "imageConfig": {"aspectRatio": "4:5"},
    }


def test_gemini_client_reports_blocked_and_failed_requests():
    session = Mock()
    session.post.return_value = _response(
        {"promptFeedback": {"blockReason": "SAFETY"}}
    )
    with pytest.raises(ArtGenerationError, match="SAFETY"):
        GeminiImageClient(api_key="k", session=session).generate("p")
    session.post.return_value = _response(
        {"error": {"message": "API key not valid"}}, status=400
    )
    with pytest.raises(ArtGenerationError, match="API key not valid"):
        GeminiImageClient(api_key="k", session=session).generate("p")


def test_artwork_stage_gates_render_and_clears_stale_image(workspace, monkeypatch):
    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    monkeypatch.setattr(review_ui, "art_service_problem", lambda: None)
    monkeypatch.setattr(
        review_ui, "load_brand", lambda brand_id: Brand.from_mapping(PAINTING_BRAND)
    )
    workspace.write({**POST, "brand_id": "demo", "design_prompt": "A monk by a lake"})

    stages = {s["id"]: s for s in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["artwork"]["can_run"] is True
    assert stages["instagram_image"]["can_run"] is False
    assert stages["instagram_image"]["reason"] == "Generate the artwork first."
    with pytest.raises(ValueError, match="artwork"):
        review_ui.run_production_stage("post", "post_001", "instagram_image")

    workspace.render()
    client = Mock()
    client.generate.return_value = (b"\xff\xd8\xffjpeg", "image/jpeg")
    monkeypatch.setattr(
        review_ui,
        "generate_post_artwork",
        lambda post_id, art_style: art_generator.generate_post_artwork(
            post_id, art_style, client=client
        ),
    )
    review_ui.run_production_stage("post", "post_001", "artwork")

    assert (workspace.assets / "post_001_art.jpg").read_bytes() == b"\xff\xd8\xffjpeg"
    assert "Visual style: Warm parchment" in client.generate.call_args.args[0]
    assert not media_renderer.post_image_path("post_001").exists()
    stages = {s["id"]: s for s in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["artwork"]["status"] == "ready"
    assert stages["instagram_image"]["can_run"] is True


from art_generator import CloudflareImageClient, get_image_client

JPEG = b"\xff\xd8\xff\xe0fake"


def test_cloudflare_client_requests_flux_and_decodes_image():
    session = Mock()
    session.post.return_value = _response(
        {"success": True, "result": {"image": base64.b64encode(JPEG).decode()}}
    )
    client = CloudflareImageClient(api_token="t", account_id="acc", session=session)

    assert client.generate("p" * 3000) == (JPEG, "image/jpeg")
    call = session.post.call_args
    assert call.args[0] == (
        "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/"
        "@cf/black-forest-labs/flux-1-schnell"
    )
    assert call.kwargs["headers"] == {"Authorization": "Bearer t"}
    assert len(call.kwargs["json"]["prompt"]) == 2048
    assert call.kwargs["json"]["steps"] == 8

    session.post.return_value = _response(
        {"success": False, "errors": [{"message": "Authentication error"}]},
        status=401,
    )
    with pytest.raises(ArtGenerationError, match="Authentication error"):
        client.generate("p")


def test_image_client_follows_art_provider_setting(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "t")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("ART_PROVIDER", "cloudflare")
    assert isinstance(get_image_client(), CloudflareImageClient)
    monkeypatch.setenv("ART_PROVIDER", "gemini")
    assert isinstance(get_image_client(), GeminiImageClient)
    monkeypatch.setenv("ART_PROVIDER", "other")
    with pytest.raises(ArtGenerationError, match="ART_PROVIDER"):
        get_image_client()


def test_manual_artwork_upload_and_prompt(workspace, monkeypatch):
    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    monkeypatch.setattr(
        review_ui, "load_brand", lambda brand_id: Brand.from_mapping(PAINTING_BRAND)
    )
    record = {**POST, "brand_id": "demo", "design_prompt": "A monk by a lake"}
    workspace.write({**record, "status": "Draft"})
    assert "A monk by a lake" in review_ui.get_art_prompt("post", "post_001")
    with pytest.raises(ValueError, match="Approve"):
        review_ui.upload_artwork("post", "post_001", JPEG)

    workspace.write(record)
    workspace.render()
    with pytest.raises(ArtGenerationError, match="PNG, JPEG, or WebP"):
        review_ui.upload_artwork("post", "post_001", b"<html>not an image")

    review_ui.upload_artwork("post", "post_001", JPEG)
    assert (workspace.assets / "post_001_art.jpg").read_bytes() == JPEG
    assert not media_renderer.post_image_path("post_001").exists()
    stages = {s["id"]: s for s in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["artwork"]["status"] == "ready"
    assert stages["instagram_image"]["can_run"] is True


import video_renderer

IMAGE_REEL = {
    **POST,
    "brand_id": None,
    "format_id": "image_reel",
    "platform_id": "instagram",
    "design_prompt": "A woman with a clay bowl on a village path",
    "music_cue": "Slow flute",
}


def test_image_reel_format_resolves_for_instagram_with_thinker():
    from config_loader import resolve_generation_request
    from content_models import GeneratedContent

    request = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="image_reel",
        platform_id="instagram",
        thinker_id="buddha",
    )
    assert request.content_format.content_kind == "post"
    assert request.content_format.aspect_ratio == "9:16"
    content = GeneratedContent.from_text(
        "Title: T\nMain_point: M\nSupporting_copy: S\nVisual_labels: None\n"
        "Design_prompt: D\nMusic_cue: Slow flute\nCaption: C",
        request.content_format.content_fields,
    )
    assert content.fields["music_cue"] == "Slow flute"


def test_image_reel_art_is_vertical():
    record = {**IMAGE_REEL}
    assert art_generator.art_aspect_ratio(record) == "9:16"
    assert "9:16 vertical" in art_generator.build_art_prompt(record)
    assert "4:5" in art_generator.build_art_prompt({**POST, "design_prompt": "x"})


def test_image_reel_layers_split_art_and_text(tmp_path):
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    full = build_post_html(IMAGE_REEL, artwork=art)
    text = build_post_html(IMAGE_REEL, artwork=art, layer="text")
    background = build_post_html(IMAGE_REEL, artwork=art, layer="background")

    assert "height: 1920px" in full and "<img" in full
    assert "<img" not in text and 'class="layer-text look-none"' in text
    assert 'class="layer-background look-none"' in background
    with pytest.raises(MediaRenderError, match="artwork"):
        build_post_html(IMAGE_REEL)


def test_ffmpeg_command_renders_silent_vertical_clip(tmp_path):
    layers = [(tmp_path / f"t{n}.png", start) for n, start in enumerate((0, 1.5, 4.0))]
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", layers, tmp_path / "out.mp4", 10
    )
    filters = command[command.index("-filter_complex") + 1]
    assert "s=1080x1920" in filters
    assert [f"fade=t=in:st={s}:" in filters for s in (1.5, 4.0)] == [True] * 2
    assert "[1:v]format=rgba[t1]" in filters  # first line: no fade, frame one
    assert video_renderer.TEXT_REVEALS[0] == ("title", 0)
    assert "[v3]scale=out_range=tv" in filters
    assert "-an" in command and command[-1].endswith("out.mp4")
    assert command[command.index("-t") + 1] == "10"


def test_image_reel_pipeline_adds_video_and_blocks_api_publish(workspace, monkeypatch):
    monkeypatch.setattr(video_renderer, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    workspace.write(IMAGE_REEL)

    stages = {s["id"]: s for s in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["reel_video"]["reason"] == "Generate the artwork first."
    assert "video" not in stages
    assert stages["publishing"]["can_run"] is False
    assert stages["publishing"]["reason"] == "Render the Reel video first."

    rendered = []
    monkeypatch.setattr(
        review_ui,
        "render_image_reel_video",
        lambda post_id: rendered.append(post_id) or workspace.assets / "x.mp4",
    )
    art_generator.save_post_artwork("post_001", b"\x89PNG\r\n\x1a\nfake")
    review_ui.run_production_stage("post", "post_001", "reel_video")
    assert rendered == ["post_001"]
    with pytest.raises(ValueError, match="Reel video"):
        review_ui.publish_content("post", "post_001", host=Mock(), publisher=Mock())


def test_visual_style_replaces_brand_style_and_darkens_render(tmp_path):
    record = {**IMAGE_REEL, "visual_style": "cinematic_photo"}
    prompt = art_generator.build_art_prompt(record, "Painterly parchment brand")

    assert "Photorealistic cinematic film still" in prompt
    assert "Painterly parchment brand" not in prompt
    assert "deep, natural, empty shadow" in prompt
    assert prompt.rstrip().endswith("HDR halos.")

    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    html = build_post_html(record, artwork=art)
    assert "#0E0C0B" in html and "#F5C542" in html


def test_image_reel_prompt_file_is_text_free_art_prompt():
    from config_loader import load_format, load_platform
    from post_prompt import build_post_prompt_file

    record = {**IMAGE_REEL, "visual_style": "cinematic_photo"}
    prompt = build_post_prompt_file(
        record, load_format("image_reel"), load_platform("instagram")
    )
    assert "EXACT COPY" not in prompt
    assert POST["main_point"] not in prompt
    assert "purely pictorial" in prompt


def test_image_reel_footer_shows_source_and_handle(tmp_path):
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    brand = Brand.from_mapping(
        {
            "id": "demo",
            "display_name": "Demo",
            "default_profile_id": "rational_thoughts",
            "default_format_id": "image_reel",
            "default_platform_id": "instagram",
            "template": {"handle": "@demo"},
        }
    )
    record = {
        **IMAGE_REEL,
        "caption": "Hook.\n\nTeaching: The mind leads (Dhammapada 1-2)\n\n#tag",
    }
    assert media_renderer.source_line(record) == "Dhammapada 1-2"
    html = build_post_html(record, brand, artwork=art)
    assert "Dhammapada 1-2 · @demo" in html


def test_image_reel_can_be_marked_as_posted_by_hand(workspace, monkeypatch):
    monkeypatch.setattr(video_renderer, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    monkeypatch.setattr(review_ui, "reel_video_path", video_renderer.reel_video_path)
    workspace.write(IMAGE_REEL)

    with pytest.raises(ValueError, match="Render the Reel video"):
        review_ui.mark_posted("post", "post_001")
    video = video_renderer.reel_video_path("post_001")
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"mp4")
    with pytest.raises(ValueError, match="instagram.com"):
        review_ui.mark_posted("post", "post_001", "https://example.com/x")

    record = review_ui.mark_posted(
        "post", "post_001", "https://www.instagram.com/reel/abc/"
    )
    assert record["status"] == "Published" and record["published_manually"]
    assert workspace.read()["instagram_permalink"].endswith("/reel/abc/")
    stages = {s["id"]: s for s in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["publishing"]["status"] == "ready"
    with pytest.raises(ValueError, match="unposted"):
        review_ui.mark_posted("post", "post_001")


def _reel_workspace(workspace, monkeypatch, **extra):
    monkeypatch.setattr(video_renderer, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    monkeypatch.setattr(review_ui, "reel_video_path", video_renderer.reel_video_path)
    workspace.write({**IMAGE_REEL, **extra})
    video = video_renderer.reel_video_path("post_001")
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"mp4")
    return video


def test_image_reel_publishes_video_as_reel(workspace, monkeypatch):
    video = _reel_workspace(workspace, monkeypatch)
    host = Mock()
    host.upload.return_value = ("key", "https://cdn.example/reel.mp4")
    publisher = Mock()
    publisher.publish_reel.return_value = {
        "media_id": "m1", "permalink": "https://www.instagram.com/reel/m1/"
    }

    review_ui.publish_content("post", "post_001", host=host, publisher=publisher)

    assert host.upload.call_args.args[0] == video
    url, caption = publisher.publish_reel.call_args.args
    assert url == "https://cdn.example/reel.mp4" and caption == POST["caption"]
    assert publisher.publish_reel.call_args.kwargs["thumb_offset_ms"] == 5000
    publisher.publish_image.assert_not_called()
    record = workspace.read()
    assert record["status"] == "Published"
    assert record["instagram_permalink"].endswith("/reel/m1/")


def test_publisher_creates_reel_container_and_waits_longer():
    session = Mock()
    session.get.side_effect = [
        _response({"data": [{"quota_usage": 0, "config": {"quota_total": 100}}]}),
        _response({"status_code": "IN_PROGRESS"}),
        _response({"status_code": "FINISHED"}),
        _response({"permalink": "https://www.instagram.com/reel/x/", "is_ai_generated": True}),
    ]
    session.post.side_effect = [_response({"id": "c1"}), _response({"id": "m1"})]
    publisher = InstagramPublisher("token", "123", session=session, sleep=lambda s: None)

    result = publisher.publish_reel("https://cdn.example/r.mp4", "Hi", 5000)

    data = session.post.call_args_list[0].kwargs["data"]
    assert data["media_type"] == "REELS" and data["video_url"].endswith("r.mp4")
    assert data["thumb_offset"] == "5000" and data["share_to_feed"] == "true"
    assert data["is_ai_generated"] == "true"
    assert result == {
        "media_id": "m1", "permalink": "https://www.instagram.com/reel/x/", "ai_label": True
    }


def test_review_settings_save_caption_music_and_schedule(workspace, monkeypatch):
    video = _reel_workspace(workspace, monkeypatch)
    import music_library

    music = workspace.assets / "music"
    music.mkdir()
    (music / "slow_flute.mp3").write_bytes(b"mp3")
    monkeypatch.setattr(music_library, "MUSIC_DIRECTORY", music)

    review_ui.update_post_settings("post_001", {"caption": "New caption #one"})
    assert workspace.read()["caption"] == "New caption #one"
    assert video.exists()

    review_ui.update_post_settings("post_001", {"music_track": "slow_flute.mp3"})
    assert workspace.read()["music_track"] == "slow_flute.mp3"
    assert not video.exists()  # stale audio must be re-rendered
    with pytest.raises(ValueError, match="not in the music folder"):
        review_ui.update_post_settings("post_001", {"music_track": "x.mp3"})

    with pytest.raises(ValueError, match="future"):
        review_ui.update_post_settings(
            "post_001", {"scheduled_at": "2000-01-01T10:00:00+05:30"}
        )
    review_ui.update_post_settings(
        "post_001", {"scheduled_at": "2999-01-01T19:30:00+05:30"}
    )
    assert workspace.read()["scheduled_at"] == "2999-01-01T14:00:00+00:00"
    review_ui.update_post_settings("post_001", {"scheduled_at": None})
    assert "scheduled_at" not in workspace.read()


def test_due_reels_publish_once_and_failures_are_not_retried(workspace, monkeypatch):
    from datetime import datetime, timezone

    _reel_workspace(workspace, monkeypatch, scheduled_at="2026-10-22T10:00:00+00:00")
    host = Mock()
    host.upload.return_value = ("key", "https://cdn.example/reel.mp4")
    publisher = Mock()
    publisher.publish_reel.side_effect = InstagramPublishError("token expired")
    early = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
    late = datetime(2026, 10, 22, 11, 0, tzinfo=timezone.utc)

    assert review_ui.publish_due_posts(early, host, publisher) == []
    assert review_ui.publish_due_posts(late, host, publisher)[0][1] == "failed"
    assert "token expired" in workspace.read()["schedule_failed"]
    assert review_ui.publish_due_posts(late, host, publisher) == []
    assert publisher.publish_reel.call_count == 1

    publisher.publish_reel.side_effect = None
    publisher.publish_reel.return_value = {"media_id": "m", "permalink": None}
    record = workspace.read()
    record.pop("schedule_failed")
    workspace.write(record)
    assert review_ui.publish_due_posts(late, host, publisher)[0][1] == "published"
    assert workspace.read()["status"] == "Published"
    assert "scheduled_at" not in workspace.read()


def test_reel_uses_rendered_still_as_cover_and_cleans_up(workspace, monkeypatch):
    _reel_workspace(workspace, monkeypatch)
    workspace.render()  # the rendered 9:16 still with the copy
    host = Mock()
    host.upload.side_effect = [
        ("video-key", "https://cdn.example/reel.mp4"),
        ("cover-key", "https://cdn.example/cover.jpg"),
    ]
    publisher = Mock()
    publisher.publish_reel.return_value = {"media_id": "m1", "permalink": None}

    review_ui.publish_content("post", "post_001", host=host, publisher=publisher)

    assert publisher.publish_reel.call_args.kwargs["cover_url"].endswith("cover.jpg")
    assert [c.args[0] for c in host.delete.call_args_list] == ["video-key", "cover-key"]


def test_cover_url_replaces_thumb_offset_in_container():
    session = Mock()
    session.post.return_value = _response({"id": "c1"})
    publisher = InstagramPublisher("token", "123", session=session)
    publisher.create_reel_container("https://v.mp4", "Hi", 5000, "https://c.jpg")
    data = session.post.call_args.kwargs["data"]
    assert data["cover_url"] == "https://c.jpg" and "thumb_offset" not in data


def test_token_refresh_rewrites_only_the_token_line_weekly(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from scripts import publish_scheduled

    env = tmp_path / ".env"
    env.write_text("# note\nINSTAGRAM_ACCESS_TOKEN=old\nR2_BUCKET=b\n", encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "old")
    factory = Mock()
    factory.return_value.refresh_access_token.return_value = ("new", 5184000)
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)

    message = publish_scheduled.refresh_token_if_due(now, env, state, factory)
    assert "refreshed" in message and "new" not in message
    assert env.read_text() == "# note\nINSTAGRAM_ACCESS_TOKEN=new\nR2_BUCKET=b\n"
    assert publish_scheduled.refresh_token_if_due(now + timedelta(days=3), env, state, factory) is None
    assert publish_scheduled.refresh_token_if_due(now + timedelta(days=8), env, state, factory)
    assert factory.return_value.refresh_access_token.call_count == 2


def test_failed_token_refresh_waits_a_day(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from scripts import publish_scheduled

    env = tmp_path / ".env"
    env.write_text("INSTAGRAM_ACCESS_TOKEN=old\n", encoding="utf-8")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "old")
    factory = Mock()
    factory.return_value.refresh_access_token.side_effect = InstagramPublishError("nope")
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    state = tmp_path / "s.json"

    assert "failed" in publish_scheduled.refresh_token_if_due(now, env, state, factory)
    assert publish_scheduled.refresh_token_if_due(now + timedelta(hours=1), env, state, factory) is None
    assert env.read_text() == "INSTAGRAM_ACCESS_TOKEN=old\n"


def test_performance_groups_by_story_mode_style_and_thinker(tmp_path):
    import analytics

    records = [
        {"id": "post_a", "title": "A", "status": "Published", "instagram_media_id": "1",
         "qa_subtype": "comedy", "visual_style": "3d_render", "thinker_id": "buddha"},
        {"id": "post_b", "title": "B", "status": "Published",
         "instagram_permalink": "https://www.instagram.com/reel/b/",
         "qa_subtype": "comedy", "visual_style": "cinematic_photo", "thinker_id": "buddha"},
    ]
    publisher = Mock(_base_url="https://graph")
    insights = {
        "1": [("views", 100), ("reach", 80), ("saved", 2), ("shares", 1),
              ("total_interactions", 5), ("ig_reels_avg_watch_time", 4000)],
        "2": [("views", 50), ("reach", 40), ("saved", 0), ("shares", 3),
              ("total_interactions", 4), ("ig_reels_avg_watch_time", 2000)],
    }

    def request(method, url, **params):
        if url.endswith("/me/media"):
            return {"data": [
                {"id": "1", "permalink": "https://www.instagram.com/reel/a/", "media_product_type": "REELS"},
                {"id": "2", "permalink": "https://www.instagram.com/reel/b/", "media_product_type": "REELS"},
            ]}
        media_id = url.rsplit("/", 2)[-2]
        return {"data": [{"name": n, "values": [{"value": v}]} for n, v in insights[media_id]]}

    publisher._request.side_effect = request
    report = analytics.refresh_report(publisher, tmp_path / "perf.json", records)

    assert [row["id"] for row in report["posts"]] == ["post_a", "post_b"]
    mode = report["groups"]["Story mode"][0]
    assert mode == {"value": "comedy", "posts": 2, "avg_views": 75, "avg_reach": 60,
                    "saves": 2, "shares": 4, "avg_watch_seconds": 3.0}
    assert [g["value"] for g in report["groups"]["Visual style"]] == ["3d_render", "cinematic_photo"]
    assert analytics.cached_report(tmp_path / "perf.json")["posts"][0]["views"] == 100


def test_generated_captions_are_trimmed_to_five_hashtags():
    from content_models import trim_hashtags

    caption = "Hook.\n\nTeaching: X\n\n#a #b #c #d #e #f #g"
    assert trim_hashtags(caption) == "Hook.\n\nTeaching: X\n\n#a #b #c #d #e"
    with pytest.raises(ContentValidationError, match="5 hashtags"):
        validate_instagram_caption(caption)


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Teaching: The mind leads (Dhammapada 1-2)", "Dhammapada 1-2"),
        ("Teaching: Education as the root of freedom (Gulamgiri).", "Gulamgiri"),
        ("Teaching: Certainty (Source: Discourses 2.17)", "Discourses 2.17"),
        ("Teaching: Book learning (Reference: Kabir's dohas).", "Kabir's dohas"),
        ("Source: Meditations 12.17", "Meditations 12.17"),
    ],
)
def test_footer_source_line_handles_caption_variants(line, expected):
    assert media_renderer.source_line({"caption": f"Hook\n\n{line}\n\n#a"}) == expected


def test_portrait_styles_name_the_thinker_and_invite_a_reference():
    base = {**IMAGE_REEL, "profile_id": "rational_thoughts", "thinker_id": "buddha"}
    statue = art_generator.build_art_prompt({**base, "visual_style": "thinker_statue"})
    assert "Depict as a statue or bust of The Buddha" in statue
    assert "If a reference image is attached, match the face" in statue
    portrait = art_generator.build_art_prompt({**base, "visual_style": "living_thinker"})
    assert "Depict The Buddha the way they are widely recognised" in portrait
    other = art_generator.build_art_prompt({**base, "visual_style": "conceptual_metaphor"})
    assert "Depict" not in other

def test_footer_skips_source_already_in_the_attribution(tmp_path):
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    brand = Brand.from_mapping({
        "id": "demo", "display_name": "Demo", "default_profile_id": "rational_thoughts",
        "default_format_id": "image_reel", "default_platform_id": "instagram",
        "template": {"handle": "@demo"},
    })
    record = {**IMAGE_REEL, "supporting_copy": "— Epictetus, Discourses 2.17",
              "caption": "Hook\n\nTeaching: X (Source: Discourses 2.17)\n\n#a"}
    html = build_post_html(record, brand, artwork=art)
    assert '<div class="handle">@demo</div>' in html


def test_tidy_caption_splits_one_paragraph_into_parts():
    from content_models import tidy_caption

    caption = ("Hook here. Try this today. Teaching: Imagined suffering "
               "(Letters to Lucilius 13.4). Send this to a friend. #a #b #c")
    assert tidy_caption(caption) == (
        "Hook here. Try this today.\n\n"
        "Teaching: Imagined suffering (Letters to Lucilius 13.4)\n\n"
        "Send this to a friend.\n\n#a #b #c"
    )
    already = "Hook.\n\nTeaching: X (Y 1)\n\nWhy?\n\n#a #b"
    assert tidy_caption(already) == already


def test_blocked_names_never_reach_the_art_prompt():
    record = {**IMAGE_REEL, "profile_id": "rational_thoughts", "thinker_id": "osho",
              "visual_style": "painterly",
              "design_prompt": "Subject: Osho in his later years, seated. Osho smiles."}
    prompt = art_generator.build_art_prompt(record)
    assert "Osho" not in prompt and "Rajneesh" not in prompt
    assert "Depict an elderly Indian mystic" in prompt
    assert "the mystic in his later years" in prompt


def test_poster_layout_puts_quote_on_top_without_title(tmp_path):
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    record = {**IMAGE_REEL, "layout": "poster", "title": "Hidden hook",
              "main_point": "We suffer more in **imagination**.",
              "supporting_copy": "— Seneca"}
    html = build_post_html(record, artwork=art)
    assert "Didot" in html and 'class="glow"' in html
    assert ".title { display: none; }" in html
    assert '<span class="hl">imagination</span>' in html
    panel = build_post_html({**record, "layout": "panel"}, artwork=art)
    assert "Didot" not in panel


def test_poster_art_prompt_opens_the_sky_and_asks_for_cinematic_quality():
    poster = art_generator.build_art_prompt({**IMAGE_REEL, "layout": "poster"})
    assert "lower 55%" in poster and "upper 35% open, luminous" in poster
    assert "Quality: a cinematic, high-end image" in poster
    panel = art_generator.build_art_prompt({**IMAGE_REEL})
    assert "upper 35%" not in panel and "Quality: a cinematic" in panel


def test_poster_video_reveals_quote_first_and_layout_can_be_switched(workspace, monkeypatch):
    assert video_renderer.POSTER_REVEALS[0] == ("quote", 0)
    _reel_workspace(workspace, monkeypatch)
    workspace.render()
    review_ui.update_post_settings("post_001", {"layout": "poster"})
    assert workspace.read()["layout"] == "poster"
    assert not media_renderer.post_image_path("post_001").exists()
    with pytest.raises(ValueError, match="Layout"):
        review_ui.update_post_settings("post_001", {"layout": "grid"})


def test_poster_drops_old_bottom_text_area_instructions():
    record = {**IMAGE_REEL, "layout": "poster",
              "design_prompt": "Color: Amber and teal grade, with the bottom 40% fading into deep, rich shadows.\nSetting: a road."}
    prompt = art_generator.build_art_prompt(record)
    assert "Color: Amber and teal grade." in prompt and "bottom 40%" not in prompt
    assert "Setting: a road." in prompt


def test_video_clips_are_accepted_as_reel_art_only(workspace, monkeypatch):
    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    clip = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    assert art_generator.detect_video_type(clip) == "video/mp4"
    assert art_generator.detect_video_type(b"\x00\x00\x00\x14ftypqt  ") == "video/quicktime"
    workspace.write(IMAGE_REEL)
    saved = art_generator.save_post_artwork("post_001", clip)
    assert saved.suffix == ".mp4" and art_generator.is_video_artwork(saved)
    assert art_generator.artwork_path("post_001") == saved
    workspace.write({**POST, "id": "post_002"})
    with pytest.raises(ArtGenerationError, match="one-image Reels"):
        art_generator.save_post_artwork("post_002", clip)


def test_motion_clip_command_loops_crops_and_overlays(tmp_path):
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "clip.mp4", [(tmp_path / "chrome.png", 0)],
        tmp_path / "out.mp4", 8, motion_clip=True, clip_zoom=1.11,
    )
    assert command[command.index("-stream_loop") + 1] == "-1"
    filters = command[command.index("-filter_complex") + 1]
    assert "force_original_aspect_ratio=increase" in filters
    assert "crop=1080:1920:(iw-1080)/2:0" in filters
    assert "zoompan" not in filters and "noise=" in filters
    assert "-maxrate" in command


def test_effect_overlays_move_under_the_text_and_can_be_chosen(tmp_path, workspace, monkeypatch):
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [(tmp_path / "t.png", 0)], tmp_path / "o.mp4", 8,
        tmp_path / "m.mp3",
        effects=[(tmp_path / "s1.png", "0", "-mod(t*46,1920)"),
                 (tmp_path / "s2.png", "-mod(t*540,1080)", "-1920+mod(t*370,1920)")],
    )
    filters = command[command.index("-filter_complex") + 1]
    assert "overlay=x='0':y='-mod(t*46,1920)'" in filters and "[ve0]" in filters
    assert filters.index("mod(t*370") < filters.index("[v0][t1]")  # effects under text
    assert "[4:a]" in filters  # music index shifts past the effect inputs
    plain = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [(tmp_path / "t.png", 0)], tmp_path / "o.mp4", 8)
    assert "vbase" not in plain[plain.index("-filter_complex") + 1]

    assert video_renderer._scroll(-46, 1920) == "-mod(t*46,1920)"
    assert video_renderer._scroll(1500, 1920) == "-1920+mod(t*1500,1920)"
    assert video_renderer._scroll(0, 1080) == "0"
    assert video_renderer.effect_for({"sparks": True}) == "sparks"  # legacy records
    assert video_renderer.effect_for({"sparks": True, "effect": "rain"}) == "rain"
    assert video_renderer.effect_for({}) is None
    assert set(video_renderer.VIDEO_EFFECTS) == {"sparks", "meteors", "rain", "snow", "sunlight"}

    _reel_workspace(workspace, monkeypatch)
    review_ui.update_post_settings("post_001", {"sparks": True})
    assert workspace.read()["sparks"] is True
    review_ui.update_post_settings("post_001", {"effect": "meteors"})
    record = workspace.read()
    assert record["effect"] == "meteors" and "sparks" not in record
    with pytest.raises(ValueError, match="Effect must be"):
        review_ui.update_post_settings("post_001", {"effect": "hail"})
    review_ui.update_post_settings("post_001", {"effect": None})
    assert video_renderer.effect_for(workspace.read()) is None
    assert not video_renderer.reel_video_path("post_001").exists()


def test_feed_post_poster_layout_and_conversion_to_reel(tmp_path, workspace, monkeypatch):
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    poster = build_post_html({**POST, "layout": "poster"}, artwork=art)
    assert "height: 1350px" in poster and "Didot" in poster
    prompt = art_generator.build_art_prompt({**POST, "layout": "poster", "design_prompt": "x"})
    assert "4:5 portrait" in prompt and "upper 40% open" in prompt

    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    workspace.write({**POST, "design_prompt": "A monk", "status": "Approved"})
    review_ui.update_post_settings("post_001", {"layout": "poster"})
    assert workspace.read()["layout"] == "poster"
    with pytest.raises(ValueError, match="feed posts"):
        review_ui.update_post_settings("post_001", {"music_track": None})
    review_ui.update_post_settings("post_001", {"supporting_copy": " — The Buddha "})
    assert workspace.read()["supporting_copy"] == "— The Buddha"
    with pytest.raises(ValueError, match="cannot be empty"):
        review_ui.update_post_settings("post_001", {"main_point": "  "})
    record = review_ui.convert_to_reel("post_001")
    assert record["format_id"] == "image_reel" and record["platform_id"] == "instagram"
    assert record["music_cue"] and workspace.read()["layout"] == "poster"


def test_meteors_are_timed_flashes_in_the_upper_sky(tmp_path):
    strips = [tmp_path / "m0.png", tmp_path / "m1.png", tmp_path / "m2.png"]
    events = video_renderer._meteor_events(strips, 5, 7, 8)
    assert len(events) == 7 and {event[0] for event in events} == set(strips)
    starts = [timing[0] for _, _, _, timing in events]
    assert starts == sorted(starts) and all(0 < start < 8 for start in starts)
    for _, x, y, (start, length) in events:
        assert x.split("-")[0].isdigit() and f"*(t-{start})" in y
        assert int(y.split("+")[0]) <= 200  # starts high, so it stays in the sky
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [], tmp_path / "o.mp4", 8, effects=events[:1])
    filters = command[command.index("-filter_complex") + 1]
    assert "fade=t=in" in filters and "fade=t=out" in filters  # flares and fades
    assert ":enable='between(t," in filters


def test_simplify_post_text_suggests_without_saving(workspace, monkeypatch):
    workspace.write({**POST, "status": "Approved"})
    calls = []
    monkeypatch.setattr(
        review_ui, "simplify_copy",
        lambda record, fresh=False: calls.append(fresh) or {**record, "title": "New"},
    )
    assert review_ui.simplify_post_text("post_001", fresh=True)["title"] == "New"
    assert calls == [True] and workspace.read()["title"] == POST["title"]  # not saved
    workspace.write({**POST, "status": "Published"})
    with pytest.raises(ValueError, match="published"):
        review_ui.simplify_post_text("post_001")


def test_poster_text_turns_dark_on_bright_art(tmp_path, monkeypatch):
    import media_renderer
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    record = {**IMAGE_REEL, "layout": "poster"}
    for brightness, tone in ((200, "light"), (120, "mid"), (60, "dark"), (None, "dark")):
        monkeypatch.setattr(media_renderer, "_region_brightness", lambda *a, b=brightness: b)
        assert media_renderer.text_tone(art, record) == tone
        assert f"tone-{tone}" in build_post_html(record, artwork=art)
    assert media_renderer.text_tone(None, record) == "dark"


def test_designed_posts_put_exact_words_in_the_art_prompt_and_render_whole(tmp_path):
    record = {
        **IMAGE_REEL, "profile_id": "rational_thoughts", "subtype": "mind_states",
        "visual_style": "illustrated_watercolor", "brand_id": "default",
        "title": "Where is your **mind**?",
        "main_point": "**Regret** is when the mind is in the past.\n**Peace** is when the mind is here.",
        "supporting_copy": "— inspired by the Buddha",
        "design_prompt": "Cream page, one small monk beside each line.",
    }
    assert art_generator.is_designed(record)
    assert not art_generator.is_designed({**record, "subtype": "mirror"})
    prompt = art_generator.build_art_prompt(record)
    assert 'Headline: "Where is your mind?"' in prompt
    assert '- "Regret is when the mind is in the past."' in prompt
    assert '"@buddha.realteachings"' in prompt and "Regret, Peace" in prompt
    assert "purely pictorial" not in prompt and "watercolor" in prompt

    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    html = build_post_html(record, artwork=art)
    assert "object-fit: contain" in html and "Regret" not in html  # no overlay


def test_designed_reel_video_moves_the_whole_picture_gently(tmp_path):
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [], tmp_path / "o.mp4", 8,
        zoom=video_renderer.DESIGNED_ZOOM_AMOUNT)
    assert "zoompan=z='1+0.025*on/240'" in command[command.index("-filter_complex") + 1]


def test_scheduled_post_retries_network_errors_then_gives_up(workspace, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from instagram_publisher import InstagramPublishError
    now = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    workspace.write({**IMAGE_REEL, "status": "Approved", "caption": "Hook line\n\n#Buddhism",
                     "scheduled_at": (now - timedelta(minutes=30)).isoformat()})
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        raise InstagramPublishError("Could not reach Instagram (ConnectionError).", transient=True)

    monkeypatch.setattr(review_ui, "publish_content", flaky)
    publisher = Mock()
    publisher.recent_media.return_value = []
    outcome = review_ui.publish_due_posts(now=now, publisher=publisher)
    assert outcome[0][1] == "retrying"
    record = workspace.read()
    assert record["schedule_attempts"] == 1 and "schedule_failed" not in record
    # Not retried before the wait is over.
    assert review_ui.publish_due_posts(now=now + timedelta(minutes=2), publisher=publisher) == []
    later = now
    for wait in review_ui.SCHEDULE_RETRY_MINUTES:
        later += timedelta(minutes=wait)
        review_ui.publish_due_posts(now=later, publisher=publisher)
    record = workspace.read()
    assert record["schedule_failed"].startswith("Could not reach")
    assert len(calls) == len(review_ui.SCHEDULE_RETRY_MINUTES) + 1


def test_retry_after_timeout_finds_the_post_instead_of_posting_twice(workspace, monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 23, 3, 30, tzinfo=timezone.utc)
    workspace.write({**IMAGE_REEL, "status": "Approved", "caption": "Hook line\n\n#Buddhism",
                     "scheduled_at": "2026-10-23T03:00:00+00:00", "schedule_attempts": 1,
                     "schedule_retry_at": (now - timedelta(minutes=1)).isoformat()})
    monkeypatch.setattr(review_ui, "publish_content", Mock(side_effect=AssertionError("posted twice")))
    publisher = Mock()
    publisher.recent_media.return_value = [
        {"id": "9", "caption": "Hook line\n\n#Buddhism", "timestamp": "2026-10-23T03:01:10+0000",
         "permalink": "https://instagram.com/reel/x"}]
    assert review_ui.publish_due_posts(now=now, publisher=publisher)[0][1] == "published"
    record = workspace.read()
    assert record["status"] == "Published" and record["instagram_media_id"] == "9"
    assert "schedule_attempts" not in record


def test_non_network_errors_fail_at_once(workspace, monkeypatch):
    from datetime import datetime, timezone
    from instagram_publisher import InstagramPublishError
    now = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    workspace.write({**IMAGE_REEL, "status": "Approved", "caption": "c #Buddhism",
                     "scheduled_at": "2026-10-23T02:00:00+00:00"})
    monkeypatch.setattr(review_ui, "publish_content",
                        Mock(side_effect=InstagramPublishError("Invalid OAuth access token.")))
    assert review_ui.publish_due_posts(now=now)[0][1] == "failed"
    assert workspace.read()["schedule_failed"] == "Invalid OAuth access token."


def test_art_prompt_carries_scenery_and_weather_and_they_can_change(workspace, monkeypatch):
    record = {**IMAGE_REEL, "profile_id": "rational_thoughts", "design_prompt": "A monk sits.",
              "scenery": "desert_dunes", "weather": "misty_morning"}
    prompt = art_generator.build_art_prompt(record)
    assert "Place (use this even if the scene above says otherwise): Wind-rippled sand dunes" in prompt
    assert "Thick morning mist" in prompt

    monkeypatch.setattr(art_generator, "GENERATED_ASSETS_DIRECTORY", workspace.assets)
    workspace.write({**record, "status": "Approved"})
    review_ui.update_post_settings("post_001", {"scenery": "sea_cave", "weather": None})
    saved = workspace.read()
    assert saved["scenery"] == "sea_cave" and "weather" not in saved
    with pytest.raises(ValueError, match="Unknown scenery"):
        review_ui.update_post_settings("post_001", {"scenery": "moon_base"})


def test_art_prompt_drops_space_for_text_phrases():
    record = {**IMAGE_REEL, "profile_id": "rational_thoughts", "visual_style": None,
              "design_prompt": "Color: deep indigo, with a luminous open space in the upper third for text. "
                               "Quiet sky to leave room for the title overlay."}
    prompt = art_generator.build_art_prompt(record)
    scene = prompt[prompt.index("Scene:"):]
    assert "for text" not in scene and "title" not in scene
    assert "luminous open space in the upper third." in scene


def test_weather_look_tints_existing_art_and_brings_its_effect(tmp_path, workspace, monkeypatch):
    import media_renderer
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    record = {**IMAGE_REEL, "layout": "poster", "weather": "monsoon_rain", "weather_look": True}
    html = build_post_html(record, artwork=art)
    assert "look-monsoon_rain" in html and '<div class="look"></div>' in html
    assert "look-none" in build_post_html({**record, "weather_look": False}, artwork=art)
    # Bright sunny art turns dark under a rain look, so the text stays light.
    monkeypatch.setattr(media_renderer, "_region_brightness", lambda *a: 200)
    assert media_renderer.text_tone(art, record) == "dark"
    assert media_renderer.text_tone(art, {**record, "weather_look": False}) == "light"

    assert video_renderer.effect_for(record) == "rain"
    assert video_renderer.effect_for({**record, "weather": "snowfall"}) == "snow"
    assert video_renderer.effect_for({**record, "effect": None}) is None  # chose no effect
    assert video_renderer.effect_for({**record, "effect": "meteors"}) == "meteors"

    _reel_workspace(workspace, monkeypatch, weather="monsoon_rain", profile_id="rational_thoughts")
    review_ui.update_post_settings("post_001", {"weather_look": True})
    assert workspace.read()["weather_look"] is True
    assert not video_renderer.reel_video_path("post_001").exists()
    with pytest.raises(ValueError, match="on or off"):
        review_ui.update_post_settings("post_001", {"weather_look": "yes"})


def test_generate_artwork_is_off_with_a_reason_when_no_image_service(workspace, monkeypatch):
    monkeypatch.setattr(review_ui, "art_service_problem",
                        lambda: "No image service is connected (CLOUDFLARE_AI_TOKEN is empty in .env).")
    workspace.write({**IMAGE_REEL, "status": "Approved", "design_prompt": "A monk."})
    stages = {stage["id"]: stage for stage in review_ui.get_pipeline("post", "post_001")["stages"]}
    artwork = stages["artwork"]
    assert artwork["can_run"] is False and "Copy art prompt" in artwork["reason"]
    monkeypatch.setattr(review_ui, "art_service_problem", lambda: None)
    stages = {stage["id"]: stage for stage in review_ui.get_pipeline("post", "post_001")["stages"]}
    assert stages["artwork"]["can_run"] is True


def test_reel_goes_to_facebook_after_instagram_and_facebook_errors_do_not_undo_it(workspace, monkeypatch):
    from facebook_publisher import FacebookPublishError
    _reel_workspace(workspace, monkeypatch, status="Approved", caption="Hook\n\n#Buddhism")
    host = Mock()
    host.upload.return_value = ("key", "https://cdn.example/reel.mp4")
    publisher = Mock()
    publisher.publish_reel.return_value = {"media_id": "m1", "permalink": "https://www.instagram.com/reel/m1/"}
    monkeypatch.setattr(review_ui, "facebook_auto_enabled", lambda: True)
    monkeypatch.setattr(review_ui, "threads_configured", lambda: False)
    calls = []

    def failing_facebook(content_id, **kwargs):
        calls.append(content_id)
        raise FacebookPublishError("Facebook returned HTTP 400: Invalid token")

    monkeypatch.setattr(review_ui, "post_to_facebook", failing_facebook)
    result = review_ui.publish_content("post", "post_001", host=host, publisher=publisher)
    assert calls == ["post_001"] and result["facebook"]["error"].endswith("Invalid token")
    assert workspace.read()["status"] == "Published"  # Instagram post stands

    _reel_workspace(workspace, monkeypatch, status="Approved", caption="Hook\n\n#Buddhism",
                    share_to_facebook=False)
    calls.clear()
    review_ui.publish_content("post", "post_001", host=host, publisher=publisher)
    assert calls == []  # this Reel opted out


def test_performance_report_lists_hashtags_and_sorts_by_reach(tmp_path, monkeypatch):
    import analytics
    assert analytics.hashtags_of("Hook #Buddhism\n\nSource\n\n#Dhammapada #Mindfulness #Dharma #Grief") == [
        "#Buddhism", "#Dhammapada", "#Mindfulness", "#Dharma", "#Grief"]
    assert analytics.hashtags_of("No tags here, issue#4") == []
    cache = tmp_path / "performance.json"
    cache.write_text(json.dumps({"fetched_at": "x", "groups": {}, "posts": [
        {"id": "post_001", "reach": 5}, {"id": "post_002", "reach": 50}]}))
    monkeypatch.setattr(analytics, "load_post", lambda cid: {"caption": f"{cid} #Buddhism #Zen"})
    report = analytics.cached_report(cache)
    assert [row["id"] for row in report["posts"]] == ["post_002", "post_001"]
    assert report["posts"][0]["hashtags"] == ["#Buddhism", "#Zen"]


def test_performance_adds_facebook_views_to_match_the_app():
    import analytics
    publisher = Mock()
    publisher._base_url = "https://graph.example"
    publisher._request.side_effect = lambda method, url, **params: (
        {"data": [{"id": "m1", "permalink": "p1"}, {"id": "m2", "permalink": "p2"}]}
        if url.endswith("/me/media")
        else {"data": [{"name": "views", "values": [{"value": 192}]},
                       {"name": "reach", "values": [{"value": 146}]}]}
    )
    facebook = Mock()
    facebook._graph.return_value = {"views": 133}
    records = [
        {"id": "post_006", "instagram_media_id": "m1", "facebook_video_id": "fb1", "caption": "#Buddhism"},
        {"id": "post_007", "instagram_media_id": "m2"},
    ]
    rows = {row["id"]: row for row in analytics.fetch_performance(publisher, records, facebook=facebook)}
    assert rows["post_006"]["facebook_views"] == 133 and rows["post_006"]["total_views"] == 325
    assert rows["post_007"]["facebook_views"] is None and rows["post_007"]["total_views"] == 192
    assert facebook._graph.call_args.args[1] == "fb1"


def test_closing_line_series_and_first_comment(tmp_path, workspace, monkeypatch):
    from content_models import split_first_comment
    caption, comment = split_first_comment(
        "Real or fake?\n\nAnswer in the first comment.\n\nAnswer: Fake. Closest teaching: Dhammapada 5.\n\n#Buddhism")
    assert comment == "Fake. Closest teaching: Dhammapada 5." and "Answer:" not in caption
    assert caption.endswith("first comment.\n\n#Buddhism")
    assert split_first_comment("No answer here") == ("No answer here", None)

    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    record = {**IMAGE_REEL, "layout": "poster", "cta": "Save this for a hard day",
              "series_number": 4, "series_length": 30}
    html = build_post_html(record, artwork=art)
    assert 'class="cta"' not in html  # the closing line has its own end card
    import media_renderer
    card = media_renderer.build_end_card_html(record, None, art)
    assert "Save this for a hard day" in card and 'class="line"' in card
    assert '<div class="kicker">Day 4 of 30</div>' in html
    assert '<div class="kicker"></div>' in build_post_html(IMAGE_REEL, artwork=art)

    _reel_workspace(workspace, monkeypatch, status="Approved", profile_id="rational_thoughts",
                    caption="Hook line.\n\n#Buddhism")
    review_ui.update_post_settings("post_001", {"cta": "Follow for one teaching a day", "series": True})
    saved = workspace.read()
    assert saved["cta"] == "Follow for one teaching a day" and saved["series_number"] >= 1
    assert saved["caption"].startswith(f"Day {saved['series_number']} of 30 · 30 days with the Buddha\n\n")
    review_ui.update_post_settings("post_001", {"series": False, "cta": None})
    saved = workspace.read()
    assert "series_number" not in saved and "cta" not in saved and saved["caption"] == "Hook line.\n\n#Buddhism"
    with pytest.raises(ValueError, match="70 characters"):
        review_ui.update_post_settings("post_001", {"cta": "x" * 71})
    workspace.write({**workspace.read(), "status": "Published"})
    review_ui.update_post_settings("post_001", {"first_comment": "Source: SN 12.2"})
    assert workspace.read()["first_comment"] == "Source: SN 12.2"
    with pytest.raises(ValueError, match="already published"):
        review_ui.update_post_settings("post_001", {"cta": "Hi"})


def test_quiz_posts_hide_their_source_until_the_first_comment(tmp_path):
    from content_models import split_first_comment
    caption, comment = split_first_comment(
        "Real or fake?\n\nTeaching: Gratitude (AN 2.31-32)\n\nAnswer in the first comment.\n\n"
        "Answer: Real.\n\n#Buddhism", hide_source=True)
    assert "AN 2.31" not in caption and comment == "Real.\n\nTeaching: Gratitude (AN 2.31-32)"
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    quiz = {**IMAGE_REEL, "subtype": "real_or_fake", "caption": "x\n\nTeaching: Gratitude (AN 2.31-32)"}
    assert "AN 2.31" not in build_post_html(quiz, artwork=art)


def test_carousel_slides_render_and_publish_as_one_post(tmp_path, workspace, monkeypatch):
    import media_renderer
    from instagram_publisher import InstagramPublisher
    record = {
        **POST, "format_id": "carousel", "platform_id": "instagram_feed",
        "title": "5 signs your **mind** needs rest", "main_point": "Notice them early.",
        "slides": "1. You reread the same line\n2. Small noises feel **loud**\nPlain line",
        "supporting_copy": "Rest is part of the **path**.",
    }
    slides = media_renderer.carousel_slides(record)
    assert [slide["kind"] for slide in slides] == ["cover", "inner", "inner", "inner", "closing"]
    assert slides[1]["number"] == "01" and slides[1]["big"] == "You reread the same line"
    assert slides[3]["number"] == "" and slides[1]["counter"] == "2/5" and slides[-1]["counter"] == "5/5"
    art = tmp_path / "art.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    html = media_renderer.build_carousel_html(record, None, art, slides[1])
    assert 'class="inner tone-dark"' in html and "You reread the same line" in html

    # Publishing uploads every slide and posts one carousel.
    workspace.write({**record, "status": "Approved", "slide_count": 3, "caption": "Hook\n\n#Buddhism"})
    for number in (1, 2, 3):
        path = media_renderer.carousel_slide_path("post_001", number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpg")
    monkeypatch.setattr(review_ui, "carousel_slide_path", media_renderer.carousel_slide_path)
    monkeypatch.setattr(review_ui, "post_image_path", media_renderer.post_image_path)
    host = Mock()
    host.upload.side_effect = [("k1", "u1"), ("k2", "u2"), ("k3", "u3")]
    publisher = Mock()
    publisher.publish_carousel.return_value = {"media_id": "c1", "permalink": "https://instagram.com/p/c1/"}
    review_ui.publish_content("post", "post_001", host=host, publisher=publisher)
    assert publisher.publish_carousel.call_args.args[0] == ["u1", "u2", "u3"]
    assert workspace.read()["status"] == "Published"
    assert [call.args[0] for call in host.delete.call_args_list] == ["k1", "k2", "k3"]

    # The API client makes one item per slide, then the carousel parent.
    client = InstagramPublisher(access_token="t", account_id="a", session=Mock())
    calls = []
    client._request = lambda method, url, **params: calls.append(params) or {"id": f"id{len(calls)}", "status_code": "FINISHED"}
    client._check_quota = lambda: None
    client.wait_until_ready = lambda *a, **k: None
    client._finish = lambda container_id, timeout_seconds=None: {"media_id": container_id}
    assert client.publish_carousel(["u1", "u2"], "cap") == {"media_id": "id3"}
    assert calls[0]["is_carousel_item"] == "true" and calls[2]["media_type"] == "CAROUSEL"
    assert calls[2]["children"] == "id1,id2" and calls[2]["caption"] == "cap"


def test_scheduler_publishes_due_feed_posts_and_carousels(workspace, monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
    published = []
    monkeypatch.setattr(review_ui, "publish_content",
                        lambda kind, cid, **kw: published.append(cid) or {"permalink": "https://ig/p"})
    for format_id in ("carousel", "single_page"):
        published.clear()
        workspace.write({**POST, "format_id": format_id, "platform_id": "instagram_feed",
                         "status": "Approved", "scheduled_at": "2026-10-24T02:00:00+00:00"})
        assert review_ui.publish_due_posts(now=now)[0][1] == "published"
        assert published == ["post_001"]
    review_ui.update_post_settings("post_001", {"scheduled_at": "2030-01-01T01:00:00+00:00"})
    assert workspace.read()["scheduled_at"].startswith("2030-01-01")


def test_end_card_cross_fades_after_the_reel(tmp_path):
    command = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [(tmp_path / "t.png", 0)], tmp_path / "o.mp4", 8,
        tmp_path / "m.mp3", end_card=tmp_path / "card.jpg")
    filters = command[command.index("-filter_complex") + 1]
    assert "[main][card]xfade=transition=fade:duration=0.6:offset=7.4[out]" in filters
    assert "[3:a]" in filters  # music comes after the end card input
    total = 8 + video_renderer.END_CARD_SECONDS - video_renderer.END_CARD_FADE
    assert command[command.index("-t", command.index("-color_range")) + 1] == str(total)
    plain = video_renderer.build_ffmpeg_command(
        "ffmpeg", tmp_path / "bg.jpg", [(tmp_path / "t.png", 0)], tmp_path / "o.mp4", 8)
    assert "xfade" not in plain[plain.index("-filter_complex") + 1]
