import json
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
    with pytest.raises(ContentValidationError, match="30 hashtags"):
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
        _response({"permalink": "https://instagram.com/p/abc"}),
    ]
    session.post.side_effect = [_response({"id": "c1"}), _response({"id": "m1"})]

    result = _publisher(session).publish_image("https://cdn/x.jpg", "Caption")

    assert result == {"media_id": "m1", "permalink": "https://instagram.com/p/abc"}
    create, publish = session.post.call_args_list
    assert create.args[0] == "https://graph.example/v1/123/media"
    assert create.kwargs["data"]["image_url"] == "https://cdn/x.jpg"
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
    with pytest.raises(ValueError, match="Instagram Feed"):
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
    assert "no text" in prompt and "A monk by a lake" in prompt
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
