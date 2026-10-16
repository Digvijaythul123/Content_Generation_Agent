import json
import sys
from unittest.mock import Mock, patch

import pytest

import content_agent
from config_loader import load_format, load_platform, resolve_generation_request
from scripts import main
from profile_loader import ProfileError, load_profile
import reel_storage


def test_loads_rational_thoughts_profile():
    profile = load_profile("rational_thoughts")

    assert profile["id"] == "rational_thoughts"
    assert profile["display_name"] == "Rational Thoughts"
    assert profile["audience"]["description"] == (
        "Indian professionals aged 25-40"
    )


def test_loads_comedy_profile():
    profile = load_profile("comedy")

    assert profile["id"] == "comedy"
    assert profile["display_name"] == "Comedy"
    assert "Entertain" in profile["objectives"]


def test_single_page_format_and_instagram_feed_platform_are_configured():
    content_format = load_format("single_page")
    platform = load_platform("instagram_feed")

    assert content_format.content_kind == "post"
    assert content_format.content_fields == (
        "title",
        "main_point",
        "supporting_copy",
        "visual_labels",
        "design_prompt",
        "caption",
    )
    assert content_format.prompt_template == "single_page_generation.md"
    assert content_format.aspect_ratio == "4:5"
    assert platform.supported_format_ids == ("single_page",)
    assert platform.aspect_ratio == "4:5"


def test_qa_engineering_profile_and_linkedin_formats_are_configured():
    profile = load_profile("qa_engineering_ai")
    text_post = load_format("linkedin_text_post")
    visual_post = load_format("single_page")
    linkedin = load_platform("linkedin")

    assert profile["display_name"] == "QA Engineering & AI"
    assert any("AI-assisted" in topic for topic in profile["topics"])
    assert text_post.content_kind == "post"
    assert text_post.content_fields == ("title", "post_text")
    assert text_post.prompt_template == "linkedin_text_post.md"
    assert linkedin.supported_format_ids == (
        "linkedin_text_post",
        "single_page",
    )
    assert visual_post.id in linkedin.supported_format_ids


def test_linkedin_request_accepts_qa_text_and_visual_posts():
    text_request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
        brief="Explain how to investigate flaky tests.",
    )
    visual_request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        format_id="single_page",
        platform_id="linkedin",
        brief="Show a concise test-pyramid principle.",
    )

    assert text_request.platform.id == "linkedin"
    assert text_request.content_format.id == "linkedin_text_post"
    assert visual_request.platform.id == "linkedin"
    assert visual_request.content_format.id == "single_page"


def test_linkedin_single_page_prompt_uses_linkedin_and_exact_copy():
    from post_prompt import build_ready_design_prompt

    request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        format_id="single_page",
        platform_id="linkedin",
    )
    prompt = build_ready_design_prompt(
        {
            "title": "Reliable tests start with clear ownership",
            "main_point": "Every automated test needs an owner.",
            "supporting_copy": "Review flaky tests instead of rerunning blindly.",
            "visual_labels": "Test, Owner, Evidence",
            "design_prompt": "Use a clean technical editorial layout.",
        },
        request.content_format,
        request.platform,
    )

    assert prompt.startswith(
        "Create one finished LinkedIn social media graphic.\n"
        "Canvas: 4:5 portrait; 1080x1350."
    )
    assert "Headline: Reliable tests start with clear ownership" in prompt
    assert "Main point: Every automated test needs an owner." in prompt
    assert "Supporting copy: Review flaky tests instead of rerunning blindly." in prompt
    assert "EXACT DIAGRAM LABELS TO INCLUDE:\nTest, Owner, Evidence" in prompt


def test_linkedin_text_post_uses_profile_and_format_prompt():
    request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
        brief="Explain how AI can help review test cases.",
    )
    service = Mock()
    service.generate_reel.return_value = "generated content"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            brief=request.brief,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "QA Engineering & AI" in prompt
    assert "LinkedIn post" in prompt
    assert "Do not invent first-person work experience" in prompt
    assert "AI-assisted test design and maintenance" in prompt
    assert "Post_text:" in prompt



def test_unknown_profile_raises_clear_error():
    with pytest.raises(ProfileError, match="was not found"):
        load_profile("unknown_profile")


def test_invalid_profile_id_is_rejected():
    with pytest.raises(ProfileError, match="Invalid profile ID"):
        load_profile("../comedy")


def test_legacy_title_is_used_only_for_default_profile(tmp_path):
    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    posts_dir = tmp_path / "generated_posts"
    posts_dir.mkdir()
    (reels_dir / "legacy.json").write_text(
        json.dumps({"title": "Legacy title"}),
        encoding="utf-8",
    )
    (reels_dir / "comedy.json").write_text(
        json.dumps({"profile_id": "comedy", "title": "Comedy title"}),
        encoding="utf-8",
    )
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "content_generation.md").write_text(
        "Profile: $display_name\n"
        "Audience: $audience\n"
        "Language: $language\n"
        "Objectives:\n$objectives\n"
        "Traits: $voice_traits\n"
        "Avoid: $voice_avoid\n"
        "Topics:\n$topics\n"
        "Previous:\n$previous_titles\n",
        encoding="utf-8",
    )

    prompt_path = tmp_path / "prompts" / "content_generation.md"
    with patch.object(
        content_agent, "GENERATED_REELS_DIRECTORY", reels_dir
    ):
        with patch.object(
            content_agent, "GENERATED_POSTS_DIRECTORY", posts_dir
        ):
            with patch.object(
                content_agent, "PROMPT_TEMPLATE_PATH", prompt_path
            ):
                with patch.object(content_agent, "AIService") as service_class:
                    service = Mock()
                    service.generate_reel.return_value = "generated content"
                    service_class.return_value = service

                    rational_agent = content_agent.ContentAgent()
                    assert rational_agent.get_previous_titles() == [
                        "Legacy title"
                    ]
                    rational_agent.generate_content()
                    rational_prompt = service.generate_reel.call_args.args[0]
                    assert "Legacy title" in rational_prompt
                    assert "Comedy title" not in rational_prompt

                    service.generate_reel.reset_mock()
                    comedy_agent = content_agent.ContentAgent(
                        profile_id="comedy"
                    )
                    assert comedy_agent.get_previous_titles() == [
                        "Comedy title"
                    ]
                    comedy_agent.generate_content()
                    comedy_prompt = service.generate_reel.call_args.args[0]
                    assert "Comedy title" in comedy_prompt
                    assert "Legacy title" not in comedy_prompt
                    assert "Playful" in comedy_prompt


def test_previous_titles_include_saved_single_page_posts(tmp_path, monkeypatch):
    reels_directory = tmp_path / "generated_reels"
    posts_directory = tmp_path / "generated_posts"
    reels_directory.mkdir()
    posts_directory.mkdir()
    (posts_directory / "post_001.json").write_text(
        json.dumps(
            {
                "profile_id": "rational_thoughts",
                "brand_id": "default",
                "title": "Prior post",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        content_agent, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        content_agent, "GENERATED_POSTS_DIRECTORY", posts_directory
    )

    agent = content_agent.ContentAgent(profile_id="rational_thoughts")

    assert agent.get_previous_titles() == ["Prior post"]


def test_single_page_generation_uses_its_format_prompt_template():
    request = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="single_page",
        platform_id="instagram_feed",
        brief="Explain why confidence is not evidence.",
    )
    service = Mock()
    service.generate_reel.return_value = "generated content"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            brief=request.brief,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "Create ONE original single-page post" in prompt
    assert "For causal examples, distinguish correlation from evidence" in prompt
    assert "Visual_labels:" in prompt
    assert "Design_prompt:" in prompt
    assert "Script:" not in prompt
    assert "Explain why confidence is not evidence." in prompt


@pytest.mark.parametrize(
    ("arguments", "expected_profile"),
    [
        ([], "rational_thoughts"),
        (["--profile", "comedy"], "comedy"),
    ],
)
def test_main_saves_selected_profile_id(
    tmp_path, monkeypatch, arguments, expected_profile
):
    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_dir)
    monkeypatch.setattr(sys, "argv", ["main.py"] + arguments)

    class FakeContentAgent:
        def __init__(self, profile_id):
            self.profile = {"id": profile_id}

        def generate_content(self):
            return (
                "Title: Test title\n"
                "Hook: Test hook\n"
                "Script: Test script.\n"
                "Caption: Test caption"
            )

    def fake_generate_content(
        profile_id, brand_id, format_id, platform_id, brief=None
    ):
        del brand_id, format_id, platform_id, brief
        agent = FakeContentAgent(profile_id or "rational_thoughts")
        from config_loader import resolve_generation_request
        from content_models import GeneratedContent
        request = resolve_generation_request(profile_id=agent.profile["id"])
        content = GeneratedContent.from_text(agent.generate_content())
        return type("Result", (), {"request": request, "content": content})()

    monkeypatch.setattr(main, "generate_content", fake_generate_content)
    main.main()

    saved_record = json.loads(
        (reels_dir / "reel_001.json").read_text(encoding="utf-8")
    )
    assert saved_record["profile_id"] == expected_profile
