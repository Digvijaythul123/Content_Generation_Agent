import json
import sys
from unittest.mock import Mock, patch

import pytest

import content_agent
from config_loader import (
    load_brand,
    load_comedy_config,
    load_format,
    load_platform,
    load_profile_subtypes,
    resolve_generation_request,
)
from scripts import main
from profile_loader import ProfileError, load_profile
import reel_storage


def test_loads_rational_thoughts_profile():
    profile = load_profile("rational_thoughts")

    assert profile["id"] == "rational_thoughts"
    assert profile["display_name"] == "Critical Thinking / Rational Thoughts"
    assert profile["audience"]["description"] == (
        "Curious people interested in challenging beliefs through reason, "
        "science, critical thinking, secularism, humanism, and freedom of thought"
    )
    assert any("secularism" in topic.lower() for topic in profile["topics"])
    assert any("humanism" in topic.lower() for topic in profile["topics"])
    assert any("freedom of thought" in topic.lower() for topic in profile["topics"])


def test_rational_thoughts_prompt_uses_instagram_bio_guidance():
    request = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="reel",
        platform_id="instagram",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "challenging beliefs through reason, science, critical thinking" in prompt
    assert "Advocate secularism, humanism, and freedom of thought" in prompt
    assert "Mocking or stereotyping people based on religion or worldview" in prompt


def test_loads_comedy_profile():
    profile = load_profile("comedy")

    assert profile["id"] == "comedy"
    assert profile["display_name"] == "Comedy"
    assert "Entertain" in profile["objectives"]


def test_comedy_category_defines_ten_stable_subtypes():
    comedy = load_comedy_config()

    assert comedy["brand_id"] == "life_is_a_glitch"
    assert len(comedy["subtypes"]) == 10
    assert {item["id"] for item in comedy["subtypes"]} == {
        "relatable_everyday",
        "absurd_surreal",
        "dark_uncomfortable",
        "pov",
        "sarcastic_conversations",
        "literal_interpretation",
        "brain_vs_reality",
        "expectation_vs_reality",
        "objects_with_personalities",
        "impossible_choices",
    }


@pytest.mark.parametrize(
    ("format_id", "platform_id", "expected_fields"),
    [
        ("reel", "instagram", ("title", "hook", "script", "caption")),
        (
            "single_page",
            "instagram_feed",
            (
                "title",
                "main_point",
                "supporting_copy",
                "visual_labels",
                "design_prompt",
                "caption",
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "subtype",
    [
        "relatable_everyday",
        "absurd_surreal",
        "dark_uncomfortable",
        "pov",
        "sarcastic_conversations",
        "literal_interpretation",
        "brain_vs_reality",
        "expectation_vs_reality",
        "objects_with_personalities",
        "impossible_choices",
    ],
)
def test_comedy_subtypes_support_reels_and_single_page_posts(
    subtype, format_id, platform_id, expected_fields
):
    request = resolve_generation_request(
        category_id="comedy",
        comedy_subtype=subtype,
        format_id=format_id,
        platform_id=platform_id,
    )

    assert request.category_id == "comedy"
    assert request.comedy_subtype == subtype
    assert request.brand.display_name == "Life Is a Glitch"
    assert request.profile.id == "comedy"
    assert request.content_format.content_fields == expected_fields


def test_explicit_comedy_category_is_supported_for_linkedin_without_liag_brand():
    request = resolve_generation_request(
        category_id="comedy",
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
    )

    assert request.profile.id == "qa_engineering_ai"
    assert request.brand.display_name == "d_agnostic_being"
    assert request.content_format.content_fields == (
        "title",
        "post_text",
        "image_generation_prompt",
    )


def test_explicit_comedy_linkedin_prompt_does_not_inject_liag_brand():
    request = resolve_generation_request(
        category_id="comedy",
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            category_id=request.category_id,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "COMEDY (" in prompt
    assert "do not apply Life Is a Glitch branding" in prompt
    assert "Publishing brand: Life Is a Glitch" not in prompt


def test_selected_comedy_subtype_prompt_omits_other_subtype_definitions():
    request = resolve_generation_request(
        category_id="comedy",
        comedy_subtype="objects_with_personalities",
        format_id="reel",
        platform_id="instagram",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            category_id=request.category_id,
            comedy_subtype=request.comedy_subtype,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    subtypes = load_comedy_config()["subtypes"]
    selected = next(
        item for item in subtypes if item["id"] == "objects_with_personalities"
    )
    other_definitions = [
        item["definition"] for item in subtypes if item is not selected
    ]

    assert selected["definition"] in prompt
    assert all(definition not in prompt for definition in other_definitions)


def test_comedy_rejects_unknown_subtype():
    from config_loader import ConfigurationError

    with pytest.raises(ConfigurationError, match="Unknown Comedy subtype"):
        resolve_generation_request(
            category_id="comedy",
            comedy_subtype="made_up",
            format_id="reel",
            platform_id="instagram",
        )


def test_comedy_category_without_subtype_uses_appropriate_default_brand():
    request = resolve_generation_request(
        category_id="comedy",
        format_id="reel",
        platform_id="instagram",
    )

    assert request.category_id == "comedy"
    assert request.comedy_subtype is None
    assert request.profile.id == "comedy"
    assert request.brand.id == "life_is_a_glitch"


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
    assert text_post.content_fields == (
        "title",
        "post_text",
        "image_generation_prompt",
    )
    assert text_post.prompt_template == "linkedin_text_post.md"
    assert linkedin.supported_format_ids == (
        "linkedin_text_post",
        "single_page",
    )
    assert visual_post.id in linkedin.supported_format_ids


def test_qa_profile_defines_selectable_topic_pillars():
    subtypes = load_profile_subtypes("qa_engineering_ai")

    assert len(subtypes) == 8
    assert {item["id"] for item in subtypes} == {
        "testing_strategy",
        "automation_architecture",
        "ui_api_integration_testing",
        "ci_flaky_tests",
        "exploratory_debugging",
        "ai_assisted_qa",
        "llm_testing",
        "qa_communication",
    }


def test_qa_subtype_is_validated_and_resolved_for_profile():
    request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        qa_subtype="llm_testing",
        format_id="linkedin_text_post",
        platform_id="linkedin",
    )

    assert request.qa_subtype == "llm_testing"

    from config_loader import ConfigurationError

    with pytest.raises(ConfigurationError, match="Unknown QA subtype"):
        resolve_generation_request(
            profile_id="qa_engineering_ai",
            qa_subtype="made_up",
        )
    with pytest.raises(ConfigurationError, match="Unknown Story mode subtype"):
        resolve_generation_request(
            profile_id="rational_thoughts",
            qa_subtype="llm_testing",
        )


def test_selected_qa_subtype_guides_linkedin_prompt():
    request = resolve_generation_request(
        profile_id="qa_engineering_ai",
        qa_subtype="llm_testing",
        format_id="linkedin_text_post",
        platform_id="linkedin",
        brief="Explain a useful way to evaluate model responses.",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"

    with patch("content_agent.AIService", return_value=service):
        agent = content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            brief=request.brief,
            qa_subtype=request.qa_subtype,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "Selected QA topic pillar: LLM Testing & Evaluation" in prompt
    assert "representative datasets, explicit criteria, and repeatable checks" in prompt


def test_content_pipeline_passes_qa_subtype_to_agent():
    import content_pipeline

    generated = (
        "Title: QA insight\n"
        "Hook: A clear test signal matters.\n"
        "Script: Start by investigating the signal.\n"
        "Caption: Keep the feedback useful."
    )
    agent = Mock()
    agent.generate_content.return_value = generated
    with patch("content_pipeline.ContentAgent", return_value=agent) as agent_class:
        result = content_pipeline.generate_content(
            profile_id="qa_engineering_ai",
            qa_subtype="ci_flaky_tests",
        )

    assert result.request.qa_subtype == "ci_flaky_tests"
    assert agent_class.call_args.kwargs["qa_subtype"] == "ci_flaky_tests"


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


def test_personal_brand_name_and_explicit_no_brand_request():
    no_brand_request = resolve_generation_request(
        brand_id="",
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
    )

    assert load_brand("default").display_name == "d_agnostic_being"
    assert no_brand_request.brand is None
    assert no_brand_request.profile.id == "qa_engineering_ai"
    assert no_brand_request.content_format.id == "linkedin_text_post"
    assert no_brand_request.platform.id == "linkedin"
    assert no_brand_request.brand_identity_explicit is False


def test_no_brand_request_does_not_add_brand_identity_to_prompt():
    request = resolve_generation_request(
        brand_id="",
        profile_id="qa_engineering_ai",
        format_id="linkedin_text_post",
        platform_id="linkedin",
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
            brand_identity_explicit=request.brand_identity_explicit,
            brand_selected=request.brand is not None,
        )
        agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "Publishing brand:" not in prompt
    assert "d_agnostic_being" not in prompt


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
    assert "Image_generation_prompt:" in prompt
    assert "post-specific" in prompt



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


def test_generation_prompt_limits_previous_title_context(tmp_path, monkeypatch):
    reels_directory = tmp_path / "generated_reels"
    posts_directory = tmp_path / "generated_posts"
    reels_directory.mkdir()
    posts_directory.mkdir()
    for index in range(12):
        (reels_directory / f"reel_{index:03}.json").write_text(
            json.dumps(
                {
                    "profile_id": "rational_thoughts",
                    "brand_id": "default",
                    "title": f"Prior idea {index:02}",
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

    assert agent.get_previous_titles() == [
        f"Prior idea {index:02}" for index in range(2, 12)
    ]


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
        profile_id,
        brand_id,
        format_id,
        platform_id,
        brief=None,
        category_id=None,
        comedy_subtype=None,
        qa_subtype=None,
        thinker_id=None,
        visual_style=None,
        caption_language="english",
    ):
        del (
            thinker_id,
            visual_style,
            caption_language,
            brand_id,
            format_id,
            platform_id,
            brief,
            category_id,
            comedy_subtype,
            qa_subtype,
        )
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
    assert "category_id" not in saved_record
    assert "comedy_subtype" not in saved_record


def test_main_saves_comedy_category_and_selected_subtype(
    tmp_path, monkeypatch
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult

    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_dir)
    request = resolve_generation_request(
        category_id="comedy",
        comedy_subtype="pov",
        format_id="reel",
        platform_id="instagram",
    )
    result = GenerationResult(
        request=request,
        content=GeneratedContent.from_text(
            "Title: Cancelled\n"
            "Hook: The best plan is no plan.\n"
            "Script: A plan gets cancelled.\n"
            "Caption: Finally."
        ),
    )
    monkeypatch.setattr(
        main,
        "generate_content",
        lambda **kwargs: result,
    )

    assert (
        main.main(
            ["--category", "comedy", "--comedy-subtype", "pov"]
        )
        == 0
    )

    saved = json.loads(
        (reels_dir / "reel_001.json").read_text(encoding="utf-8")
    )
    assert saved["category_id"] == "comedy"
    assert saved["comedy_subtype"] == "pov"
    assert saved["brand_id"] == "life_is_a_glitch"
    assert saved["format_id"] == "reel"


def test_main_comedy_batch_rotates_subtypes_and_saves_each_draft(
    tmp_path, monkeypatch
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult

    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_dir)
    requested_subtypes = []

    def fake_generate_content(**kwargs):
        subtype = kwargs["comedy_subtype"]
        requested_subtypes.append(subtype)
        request = resolve_generation_request(
            category_id=kwargs["category_id"],
            comedy_subtype=subtype,
            format_id=kwargs["format_id"],
            platform_id=kwargs["platform_id"],
        )
        return GenerationResult(
            request=request,
            content=GeneratedContent.from_text(
                f"Title: Draft {len(requested_subtypes)}\n"
                "Hook: A setup.\n"
                "Script: A punchline.\n"
                "Caption: Funny."
            ),
        )

    monkeypatch.setattr(main, "generate_content", fake_generate_content)
    assert main.main(["--category", "comedy", "--count", "10"]) == 0

    saved_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(reels_dir.glob("*.json"))
    ]
    assert len(saved_records) == 10
    assert [record["comedy_subtype"] for record in saved_records] == (
        requested_subtypes
    )
    assert len(set(requested_subtypes)) == 10


def test_main_qa_batch_rotates_pillars_and_saves_each_draft(
    tmp_path, monkeypatch
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult

    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_dir)
    requested_subtypes = []

    def fake_generate_content(**kwargs):
        subtype = kwargs["qa_subtype"]
        requested_subtypes.append(subtype)
        request = resolve_generation_request(
            profile_id=kwargs["profile_id"],
            qa_subtype=subtype,
            format_id=kwargs["format_id"],
            platform_id=kwargs["platform_id"],
        )
        return GenerationResult(
            request=request,
            content=GeneratedContent.from_text(
                f"Title: QA Draft {len(requested_subtypes)}\n"
                "Hook: A testing problem.\n"
                "Script: A useful point.\n"
                "Caption: QA insight."
            ),
        )

    monkeypatch.setattr(main, "generate_content", fake_generate_content)
    assert (
        main.main(
            ["--profile", "qa_engineering_ai", "--count", "8"]
        )
        == 0
    )

    saved_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(reels_dir.glob("*.json"))
    ]
    assert [record["qa_subtype"] for record in saved_records] == (
        requested_subtypes
    )
    assert len(set(requested_subtypes)) == 8


def test_rational_thoughts_defines_story_modes_and_thinkers():
    from config_loader import load_profile_story_settings, load_profile_thinkers

    modes = {item["id"] for item in load_profile_subtypes("rational_thoughts")}
    thinkers = load_profile_thinkers("rational_thoughts")

    assert {"comedy", "thoughtful", "thought_provoking"} <= modes
    assert "buddha" in {item["id"] for item in thinkers}
    assert all(item["sources"] for item in thinkers)
    settings = load_profile_story_settings("rational_thoughts")
    assert settings["subtype_label"] == "Story mode"
    assert settings["reel_duration_seconds"] == {"minimum": 30, "maximum": 60}
    assert any("claim to examine" in line for line in settings["critical_lens"])


def test_thinker_and_story_mode_are_validated_for_rational_thoughts():
    from config_loader import ConfigurationError

    request = resolve_generation_request(
        profile_id="rational_thoughts",
        qa_subtype="comedy",
        thinker_id="buddha",
    )
    assert request.qa_subtype == "comedy"
    assert request.thinker_id == "buddha"

    with pytest.raises(ConfigurationError, match="Unknown thinker"):
        resolve_generation_request(
            profile_id="rational_thoughts", thinker_id="made_up"
        )
    with pytest.raises(ConfigurationError, match="does not define thinkers"):
        resolve_generation_request(
            profile_id="qa_engineering_ai", thinker_id="buddha"
        )


def test_thinker_story_prompt_includes_sources_mode_and_duration():
    request = resolve_generation_request(
        profile_id="rational_thoughts",
        qa_subtype="thought_provoking",
        thinker_id="buddha",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"

    with patch("content_agent.AIService", return_value=service):
        content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            qa_subtype=request.qa_subtype,
            thinker_id=request.thinker_id,
        ).generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "Selected thinker: The Buddha" in prompt
    assert "Kalama Sutta (Anguttara Nikaya 3.65)" in prompt
    assert "Misattributed quotes to avoid" in prompt
    assert "Selected Story mode: Thought-Provoking Dilemma" in prompt
    assert "Background and music:" in prompt
    assert "Recommended duration: 30-60 seconds" in prompt


def test_main_story_batch_rotates_modes_and_thinkers(tmp_path, monkeypatch):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult

    reels_dir = tmp_path / "generated_reels"
    reels_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_dir)

    def fake_generate_content(**kwargs):
        request = resolve_generation_request(
            profile_id=kwargs["profile_id"],
            qa_subtype=kwargs["qa_subtype"],
            thinker_id=kwargs["thinker_id"],
        )
        return GenerationResult(
            request=request,
            content=GeneratedContent.from_text(
                "Title: Story\nHook: A hook.\nScript: A story.\n"
                "Caption: Idea: a source."
            ),
        )

    monkeypatch.setattr(main, "generate_content", fake_generate_content)
    assert main.main(["--profile", "rational_thoughts", "--count", "6"]) == 0

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(reels_dir.glob("*.json"))
    ]
    assert len({record["qa_subtype"] for record in records}) == 6
    assert len({record["thinker_id"] for record in records}) == 6


def test_story_mode_picks_default_visual_style_for_posts_only():
    from config_loader import ConfigurationError

    post = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="image_reel",
        platform_id="instagram",
        qa_subtype="myth_buster",
    )
    assert post.visual_style == "thinker_statue"
    reel = resolve_generation_request(
        profile_id="rational_thoughts", qa_subtype="myth_buster"
    )
    assert reel.visual_style is None
    chosen = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="image_reel",
        platform_id="instagram",
        qa_subtype="myth_buster",
        visual_style="3d_render",
    )
    assert chosen.visual_style == "3d_render"
    with pytest.raises(ConfigurationError, match="Unknown visual style"):
        resolve_generation_request(
            profile_id="rational_thoughts", visual_style="made_up"
        )


def test_visual_style_and_thinker_name_reach_generation_prompt():
    request = resolve_generation_request(
        profile_id="rational_thoughts",
        format_id="image_reel",
        platform_id="instagram",
        thinker_id="buddha",
        visual_style="living_thinker",
    )
    service = Mock()
    service.generate_reel.return_value = "generated"
    with patch("content_agent.AIService", return_value=service):
        content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            thinker_id=request.thinker_id,
            visual_style=request.visual_style,
        ).generate_content()

    prompt = service.generate_reel.call_args.args[0]
    assert "Visual style for the Design_prompt: Living thinker" in prompt
    assert "name them in the Design_prompt subject" in prompt
    assert "ushnisha" not in prompt  # no written face descriptions
    assert "anonymous stand-in" in prompt
    assert "Subject:" in prompt and "Lighting:" in prompt

def test_hinglish_caption_option_reaches_prompt_and_rejects_unknown():
    request = resolve_generation_request(
        profile_id="rational_thoughts", format_id="image_reel", platform_id="instagram"
    )
    service = Mock()
    service.generate_reel.return_value = "generated"
    with patch("content_agent.AIService", return_value=service):
        content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            content_format=request.content_format,
            platform=request.platform,
            caption_language="hinglish",
        ).generate_content()
        with pytest.raises(ValueError, match="caption language"):
            content_agent.ContentAgent(
                profile=request.profile.to_mapping(), caption_language="klingon"
            )
    assert "Hinglish line" in service.generate_reel.call_args.args[0]


def _prompt_for(**kwargs):
    request = resolve_generation_request(
        profile_id="rational_thoughts", format_id="image_reel", platform_id="instagram",
        **kwargs,
    )
    service = Mock()
    service.generate_reel.return_value = "generated"
    with patch("content_agent.AIService", return_value=service):
        content_agent.ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            content_format=request.content_format,
            platform=request.platform,
            qa_subtype=request.qa_subtype,
            thinker_id=request.thinker_id,
        ).generate_content()
    return service.generate_reel.call_args.args[0]


def test_verified_quote_mode_uses_exact_quote_or_paraphrases_honestly():
    from config_loader import load_profile_thinkers

    epictetus = next(
        t for t in load_profile_thinkers("rational_thoughts") if t["id"] == "epictetus"
    )
    prompt = _prompt_for(qa_subtype="verified_quote", thinker_id="epictetus")
    assert any(quote["text"] in prompt for quote in epictetus["quotes"])
    assert "Supporting_copy must be: — Epictetus" in prompt

    osho = _prompt_for(qa_subtype="verified_quote", thinker_id="osho")
    assert "No verified quote is on file" in osho
    assert "inspired by Osho'" in osho


def test_critical_lens_is_applied_to_every_concept():
    prompt = _prompt_for(thinker_id="marcus_aurelius")
    assert "Critical-thinking lens" in prompt
    assert "no guru worship" in prompt
    assert "Marcus Aurelius" in prompt


def test_pipeline_rotates_thinkers_when_none_chosen(monkeypatch):
    import content_pipeline

    seen = []

    class FakeAgent:
        def __init__(self, **kwargs):
            seen.append(kwargs["thinker_id"])

        def generate_content(self):
            return "Title: T\nMain_point: M\nSupporting_copy: S\nVisual_labels: None\nDesign_prompt: D\nMusic_cue: C\nCaption: Hook #a"

    monkeypatch.setattr(content_pipeline, "ContentAgent", FakeAgent)
    result = content_pipeline.generate_content(
        profile_id="rational_thoughts", format_id="image_reel",
        platform_id="instagram", qa_subtype="verified_quote",
    )
    assert seen[0] and seen[0] != "osho"  # quote mode only picks quoted thinkers
    assert result.request.thinker_id == seen[0]
    content_pipeline.generate_content(
        profile_id="rational_thoughts", format_id="image_reel",
        platform_id="instagram", brief="Write about the news",
    )
    assert seen[1] is None  # a brief lets the model choose freely


def test_long_captions_are_shortened_once_for_threads():
    import content_pipeline

    long_caption = "Hook line. " + "More detail. " * 45 + "\nTeaching: X (Y 1)\nWhy?\n#a #b"
    good = "Hook line.\nTeaching: X (Y 1)\nWhy?\n#a #b"

    class Agent:
        def __init__(self, reply):
            self.reply = reply
        def shorten_caption(self, caption, limit):
            return self.reply

    assert content_pipeline._fit_caption_for_threads(Agent(good), long_caption) == good
    # A shorter version that drops the source line is rejected.
    assert content_pipeline._fit_caption_for_threads(
        Agent("Hook.\nWhy?\n#a #b"), long_caption) == long_caption
    assert content_pipeline._fit_caption_for_threads(Agent("x"), "short #a") == "short #a"


def test_other_modes_may_only_quote_verified_lines():
    prompt = _prompt_for(qa_subtype="mirror", thinker_id="seneca")
    assert "We suffer more often in imagination than in reality." in prompt
    assert "inspired by Seneca" in prompt
    assert "Selected Story mode: Mirror" in prompt


def test_story_mode_style_is_not_overridden_by_thinker():
    request = resolve_generation_request(
        profile_id="rational_thoughts", format_id="image_reel",
        platform_id="instagram", qa_subtype="thoughtful", thinker_id="osho",
    )
    assert request.visual_style == "living_thinker"



def test_backup_zips_content_folders_and_keeps_the_newest(tmp_path):
    import zipfile
    from datetime import datetime, timedelta, timezone
    from scripts import backup_content

    root = tmp_path / "project"
    (root / "generated_posts").mkdir(parents=True)
    (root / "generated_posts" / "post_001.json").write_text("{}")
    (root / "music").mkdir()
    (root / "music" / "a.mp3").write_bytes(b"mp3")
    (root / ".env").write_text("SECRET=1")
    dest = tmp_path / "backups"

    for day in range(6):
        backup_content.create_backup(dest, root, keep=4, now=datetime(2026, 10, 1 + day))
    zips = sorted(dest.glob("content_*.zip"))
    assert len(zips) == 4 and zips[-1].name == "content_2026-10-06_0000.zip"
    names = zipfile.ZipFile(zips[-1]).namelist()
    assert "generated_posts/post_001.json" in names and "music/a.mp3" in names
    assert not any(".env" in name for name in names)

    state = tmp_path / "state.json"
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    kwargs = dict(destination=dest, root=root, state_path=state)
    assert "backup saved" in backup_content.backup_if_due(now=now, **kwargs)
    assert backup_content.backup_if_due(now=now + timedelta(days=3), **kwargs) is None
