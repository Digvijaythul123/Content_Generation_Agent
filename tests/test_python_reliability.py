import json
import importlib
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest
import requests

from ai_service import AIService, AIServiceError
from content_agent import ContentAgent
from config_loader import resolve_generation_request
from profile_loader import load_profile
import reel_storage
from reel_storage import ReelStorageError, create_reel, load_reel, save_reel
from scripts import review_ui

# Sample content records used by tests (independent of the user's content).
FIXTURES_DIRECTORY = Path(__file__).parent / "fixtures"


def test_create_reel_uses_first_available_filename_and_does_not_overwrite(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", tmp_path)
    (tmp_path / "reel_001.json").write_text(
        json.dumps({"id": "reel_001", "title": "Existing"}),
        encoding="utf-8",
    )
    (tmp_path / "reel_003.json").write_text(
        json.dumps({"id": "reel_003", "title": "Also existing"}),
        encoding="utf-8",
    )

    reel_id, path = create_reel({"title": "New", "status": "Draft"})

    assert reel_id == "reel_002"
    assert path == tmp_path / "reel_002.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "id": "reel_002",
        "title": "New",
        "status": "Draft",
    }
    assert json.loads(
        (tmp_path / "reel_001.json").read_text(encoding="utf-8")
    )["title"] == "Existing"


def test_storage_uses_project_path_outside_current_directory(
    tmp_path, monkeypatch
):
    data_directory = tmp_path / "project" / "generated_reels"
    unrelated_directory = tmp_path / "elsewhere"
    unrelated_directory.mkdir()
    monkeypatch.chdir(unrelated_directory)
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", data_directory
    )

    save_reel("reel_001", {"id": "reel_001", "status": "Draft"})

    assert load_reel("reel_001") == {"id": "reel_001", "status": "Draft"}
    assert (data_directory / "reel_001.json").is_file()


@pytest.mark.parametrize("reel_id", ["../outside", "/tmp/escape", ""])
def test_storage_rejects_unsafe_reel_ids(reel_id):
    with pytest.raises(ReelStorageError, match="Invalid reel ID"):
        load_reel(reel_id)


@pytest.mark.parametrize(
    ("command", "status"),
    [("approve_reel", "Approved"), ("reject_reel", "Rejected")],
)
def test_review_commands_preserve_other_record_fields(
    tmp_path, monkeypatch, command, status
):
    data_directory = tmp_path / "project" / "generated_reels"
    other_directory = tmp_path / "elsewhere"
    data_directory.mkdir(parents=True)
    other_directory.mkdir()
    record = {
        "id": "reel_001",
        "title": "Keep this title",
        "profile_id": "comedy",
        "metadata": {"source": "test"},
        "status": "Draft",
    }
    (data_directory / "reel_001.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", data_directory
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", tmp_path / "assets"
    )
    monkeypatch.chdir(other_directory)
    monkeypatch.setattr(sys, "argv", [f"{command}.py", "reel_001"])

    assert importlib.import_module(f"scripts.{command}").main() == 0

    saved_record = json.loads(
        (data_directory / "reel_001.json").read_text(encoding="utf-8")
    )
    assert saved_record == {**record, "status": status}
    history = (tmp_path / "assets" / "reel_001_history.jsonl").read_text(
        encoding="utf-8"
    )
    assert f'"decision": "{status}"' in history


@pytest.mark.parametrize("command", ["approve_reel", "reject_reel"])
def test_review_commands_only_change_draft_reels(
    tmp_path, monkeypatch, command
):
    record = {"id": "reel_001", "title": "Done", "status": "Approved"}
    (tmp_path / "reel_001.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", tmp_path)
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", tmp_path / "assets"
    )
    monkeypatch.setattr(sys, "argv", [f"{command}.py", "reel_001"])

    assert importlib.import_module(f"scripts.{command}").main() == 1
    assert json.loads(
        (tmp_path / "reel_001.json").read_text(encoding="utf-8")
    ) == record


def test_ai_service_validates_http_status_and_response_shape():
    response = Mock()
    response.json.return_value = {"response": "  generated text  "}
    with patch("ai_service.requests.post", return_value=response) as post:
        assert AIService().generate_reel("prompt") == "  generated text  "
    response.raise_for_status.assert_called_once()
    assert post.call_args.kwargs["timeout"] == 180

    response.raise_for_status.side_effect = requests.HTTPError("bad status")
    with patch("ai_service.requests.post", return_value=response):
        with pytest.raises(AIServiceError, match="HTTP error"):
            AIService().generate_reel("prompt")

    response.raise_for_status.side_effect = None
    response.json.return_value = {"other": "field"}
    with patch("ai_service.requests.post", return_value=response):
        with pytest.raises(AIServiceError, match="missing non-empty text"):
            AIService().generate_reel("prompt")

    response.json.side_effect = ValueError("invalid json")
    with patch("ai_service.requests.post", return_value=response):
        with pytest.raises(AIServiceError, match="invalid JSON"):
            AIService().generate_reel("prompt")


def test_ai_service_reports_timeout():
    with patch(
        "ai_service.requests.post", side_effect=requests.Timeout("timed out")
    ):
        with pytest.raises(AIServiceError, match="timed out"):
            AIService().generate_reel("prompt")


def test_default_brand_identity_is_omitted_for_comedy_unless_explicit():
    service = Mock()
    service.generate_reel.return_value = "generated"
    comedy_profile = load_profile("comedy")
    brand = Mock(
        display_name="Rational Thoughts",
        default_profile_id="rational_thoughts",
        voice_traits=("thoughtful",),
        voice_avoid=(),
    )

    with patch("content_agent.AIService", return_value=service):
        agent = ContentAgent(
            profile_id="comedy",
            profile=comedy_profile,
            brand=brand,
        )
        agent.generate_content()
        prompt_without_brand = service.generate_reel.call_args.args[0]
        assert "Publishing brand: Rational Thoughts" not in prompt_without_brand
        assert "Brand voice traits: thoughtful" not in prompt_without_brand

        service.generate_reel.reset_mock()
        explicit_agent = ContentAgent(
            profile_id="comedy",
            profile=comedy_profile,
            brand=brand,
            brand_identity_explicit=True,
        )
        explicit_agent.generate_content()
        prompt_with_brand = service.generate_reel.call_args.args[0]

    assert "Publishing brand: Rational Thoughts" in prompt_with_brand
    assert "Brand voice traits: thoughtful" in prompt_with_brand


def test_generation_brief_is_included_in_model_prompt(tmp_path, monkeypatch):
    history_directory = tmp_path / "generated_reels"
    history_directory.mkdir()
    monkeypatch.setattr(
        "content_agent.GENERATED_REELS_DIRECTORY", history_directory
    )
    service = Mock()
    service.generate_reel.return_value = (
        "Title: Example\nHook: Hook\nScript: Script\nCaption: Caption"
    )
    brief = "Explain the hidden cost of convenience."

    with patch("content_agent.AIService", return_value=service):
        agent = ContentAgent(
            profile_id="comedy",
            profile=load_profile("comedy"),
            brief=brief,
        )
        agent.generate_content()

    model_prompt = service.generate_reel.call_args.args[0]
    assert f"Generation brief:\n{brief}" in model_prompt


def test_comedy_generation_adds_selected_subtype_without_changing_reel_contract():
    from content_models import GeneratedContent

    request = resolve_generation_request(
        category_id="comedy",
        comedy_subtype="pov",
        format_id="reel",
        platform_id="instagram",
        brief="You are relieved when an unwanted plan gets cancelled.",
    )
    service = Mock()
    service.generate_reel.return_value = (
        "Title: Plans cancelled\n"
        "Hook: POV: your calendar finally apologizes.\n"
        "Script: You celebrate the cancellation.\n"
        "Caption: The best plan was no plan."
    )

    with patch("content_agent.AIService", return_value=service):
        agent = ContentAgent(
            profile_id=request.profile.id,
            profile=request.profile.to_mapping(),
            brand=request.brand,
            content_format=request.content_format,
            platform=request.platform,
            brief=request.brief,
            brand_identity_explicit=request.brand_identity_explicit,
            category_id=request.category_id,
            comedy_subtype=request.comedy_subtype,
        )
        raw_content = agent.generate_content()

    prompt = service.generate_reel.call_args.args[0]
    content = GeneratedContent.from_text(
        raw_content, request.content_format.content_fields
    )
    assert "Subtype: POV Comedy" in prompt
    assert "Recommended duration: 8-20 seconds." in prompt
    assert "Return only the selected format's fields." in prompt
    assert tuple(content.fields) == ("title", "hook", "script", "caption")


def test_single_page_comedy_design_prompt_preserves_copy_and_comedy_direction():
    from post_prompt import build_ready_design_prompt

    request = resolve_generation_request(
        category_id="comedy",
        comedy_subtype="dark_uncomfortable",
        format_id="single_page",
        platform_id="instagram_feed",
    )
    prompt = build_ready_design_prompt(
        {
            "title": "My five-year plan",
            "main_point": "An apology to my younger self.",
            "supporting_copy": "We both made confident predictions.",
            "visual_labels": "None",
            "design_prompt": "Use one clear visual metaphor.",
        },
        request.content_format,
        request.platform,
        request.category_id,
    )

    assert "COMEDY VISUAL DIRECTION" in prompt
    assert "Headline: My five-year plan" in prompt
    assert "Do not add, omit, repeat, paraphrase, or invent any other text" in prompt


def test_generation_request_tracks_explicit_brand_selection():
    default_brand = resolve_generation_request(profile_id="comedy")
    explicit_brand = resolve_generation_request(
        profile_id="comedy", brand_id="default"
    )

    assert default_brand.brand_identity_explicit is False
    assert explicit_brand.brand_identity_explicit is True


@pytest.mark.parametrize(
    "brief_arguments",
    [
        ["--brief", "Explain why small habits compound."],
        ["--brief-file", "brief.txt"],
    ],
)
def test_main_saves_and_passes_generation_brief(
    tmp_path, monkeypatch, brief_arguments
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult
    from scripts import main

    reels_directory = tmp_path / "generated_reels"
    reels_directory.mkdir()
    brief_text = "Explain why small habits compound."
    (tmp_path / "brief.txt").write_text(brief_text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    requested_briefs = []

    def fake_generate_content(**kwargs):
        requested_briefs.append(kwargs["brief"])
        request = resolve_generation_request(
            profile_id=kwargs["profile_id"],
            brand_id=kwargs["brand_id"],
            format_id=kwargs["format_id"],
            platform_id=kwargs["platform_id"],
            brief=kwargs["brief"],
        )
        content = GeneratedContent.from_text(
            "Title: Test\nHook: Hook\nScript: Script\nCaption: Caption"
        )
        return GenerationResult(request=request, content=content)

    monkeypatch.setattr(main, "generate_content", fake_generate_content)
    assert main.main(brief_arguments) == 0

    saved_record = json.loads(
        (reels_directory / "reel_001.json").read_text(encoding="utf-8")
    )
    assert requested_briefs == [brief_text]
    assert saved_record["brief"] == brief_text


def test_main_saves_single_page_post_and_design_prompt(tmp_path, monkeypatch):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult
    from scripts import main
    import post_storage

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    monkeypatch.setattr(
        post_storage, "GENERATED_POSTS_DIRECTORY", posts_directory
    )
    monkeypatch.setattr(main, "GENERATED_ASSETS_DIRECTORY", assets_directory)
    generated = (
        "Title: Confidence isn't evidence\n"
        "Main_point: Confidence does not make a claim true.\n"
        "Supporting_copy: Ask what evidence would change your mind.\n"
        "Visual_labels: None\n"
        "Design_prompt: Editorial 4:5 layout with accurate supplied copy.\n"
        "Caption: Test the claim, not the confidence."
    )

    def fake_generate_content(**kwargs):
        request = resolve_generation_request(
            profile_id=kwargs["profile_id"],
            brand_id=kwargs["brand_id"],
            format_id=kwargs["format_id"],
            platform_id=kwargs["platform_id"],
            brief=kwargs["brief"],
        )
        content = GeneratedContent.from_text(
            generated, request.content_format.content_fields
        )
        return type("Result", (), {"request": request, "content": content})()

    monkeypatch.setattr(main, "generate_content", fake_generate_content)

    assert main.main(
        [
            "--format",
            "single_page",
            "--platform",
            "instagram_feed",
            "--brief",
            "Explain confidence versus evidence.",
        ]
    ) == 0

    saved_record = json.loads(
        (posts_directory / "post_001.json").read_text(encoding="utf-8")
    )
    assert saved_record["format_id"] == "single_page"
    assert saved_record["platform_id"] == "instagram_feed"
    assert saved_record["main_point"] == (
        "Confidence does not make a claim true."
    )
    assert (
        assets_directory / "post_001_design_prompt.txt"
    ).read_text(encoding="utf-8") == (
        "Create one finished Instagram Feed social media graphic.\n"
        "Canvas: 4:5 portrait; 1080x1350.\n\n"
        "VISUAL DESIGN DIRECTION:\n"
        "Editorial 4:5 layout with accurate supplied copy.\n\n"
        "EXACT COPY TO INCLUDE IN THE IMAGE:\n"
        "Headline: Confidence isn't evidence\n"
        "Main point: Confidence does not make a claim true.\n"
        "Supporting copy: Ask what evidence would change your mind.\n\n"
        "Render the supplied copy verbatim: preserve spelling, punctuation, "
        "capitalization, and wording. Include only the exact diagram labels "
        "listed above when that section is present. Do not add, omit, repeat, "
        "paraphrase, or invent any other text, labels, numbers, or logos. "
        "Label every diagram node clearly and connect labels to the correct "
        "nodes. Arrange the copy in a clear, readable hierarchy with "
        "sufficient contrast and spacing. "
        "Keep all text inside the canvas safe area. Do not include the caption. "
        "The finished image must communicate the idea without relying on "
        "unprovided words.\n"
    )


def test_main_saves_linkedin_text_post_and_image_prompt(
    tmp_path, monkeypatch
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult
    from scripts import main
    import post_storage

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    monkeypatch.setattr(
        post_storage, "GENERATED_POSTS_DIRECTORY", posts_directory
    )
    monkeypatch.setattr(main, "GENERATED_ASSETS_DIRECTORY", assets_directory)

    def fake_generate_content(**kwargs):
        request = resolve_generation_request(
            profile_id=kwargs["profile_id"],
            brand_id=kwargs["brand_id"],
            format_id=kwargs["format_id"],
            platform_id=kwargs["platform_id"],
            brief=kwargs["brief"],
        )
        content = GeneratedContent.from_text(
            "Title: Why tests flake\n"
            "Post_text: A flaky test is a signal to investigate.\n\n"
            "Start with the environment and shared state.\n"
            "Image_generation_prompt: A focused editorial illustration of "
            "isolated test runs revealing a shared-state problem.",
            request.content_format.content_fields,
        )
        return GenerationResult(request=request, content=content)

    monkeypatch.setattr(main, "generate_content", fake_generate_content)

    assert main.main(
        [
            "--profile",
            "qa_engineering_ai",
            "--format",
            "linkedin_text_post",
            "--platform",
            "linkedin",
            "--brief",
            "Discuss flaky test investigation.",
        ]
    ) == 0

    record = json.loads(
        (posts_directory / "post_001.json").read_text(encoding="utf-8")
    )
    assert record["profile_id"] == "qa_engineering_ai"
    assert record["format_id"] == "linkedin_text_post"
    assert record["platform_id"] == "linkedin"
    assert record["post_text"].startswith("A flaky test")
    assert record["image_generation_prompt"].startswith(
        "A focused editorial illustration"
    )
    assert "design_prompt" not in record
    assert not assets_directory.exists()


def test_review_ui_saves_explicitly_unbranded_content(
    tmp_path, monkeypatch
):
    from content_models import GeneratedContent
    from content_pipeline import GenerationResult
    from scripts import review_ui
    import post_storage

    posts_directory = tmp_path / "generated_posts"
    monkeypatch.setattr(
        post_storage, "GENERATED_POSTS_DIRECTORY", posts_directory
    )
    request = resolve_generation_request(
        brand_id="",
        profile_id="qa_engineering_ai",
        subtype="testing_strategy",
        format_id="linkedin_text_post",
        platform_id="linkedin",
    )
    result = GenerationResult(
        request=request,
        content=GeneratedContent.from_text(
            "Title: A practical QA post\n"
            "Post_text: Start with a testable quality risk.\n"
            "Image_generation_prompt: A clear editorial image about a "
            "testable quality risk.",
            request.content_format.content_fields,
        ),
    )
    monkeypatch.setattr(review_ui, "generate_content", lambda **kwargs: result)

    saved = review_ui.generate_and_save(
        {
            "brand_id": "",
            "profile_id": "qa_engineering_ai",
            "content_subtype": "testing_strategy",
            "format_id": "linkedin_text_post",
            "platform_id": "linkedin",
        }
    )

    record = json.loads(
        (posts_directory / f"{saved['id']}.json").read_text(encoding="utf-8")
    )
    assert record["brand_id"] is None
    assert record["subtype"] == "testing_strategy"
    assert record["image_generation_prompt"].startswith("A clear editorial")
    assert saved["type"] == "post"


def test_review_ui_lists_content_from_both_formats(tmp_path, monkeypatch):
    from scripts import review_ui

    reels_directory = tmp_path / "generated_reels"
    posts_directory = tmp_path / "generated_posts"
    reels_directory.mkdir()
    posts_directory.mkdir()
    (reels_directory / "reel_003.json").write_text(
        json.dumps(
            {
                "id": "reel_003",
                "title": "A reel",
                "status": "Approved",
                "profile_id": "comedy",
                "format_id": "reel",
                "platform_id": "instagram",
            }
        ),
        encoding="utf-8",
    )
    (posts_directory / "post_002.json").write_text(
        json.dumps(
            {
                "id": "post_002",
                "title": "A post",
                "status": "Draft",
                "profile_id": "rational_thoughts",
                "format_id": "single_page",
                "platform_id": "instagram_feed",
                "main_point": "A post main point",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {"reel": reels_directory, "post": posts_directory},
    )

    items = review_ui.list_content_items()

    assert [(item["id"], item["type"], item["status"]) for item in items] == [
        ("reel_003", "reel", "Approved"),
        ("post_002", "post", "Draft"),
    ]
    assert review_ui.get_content_item("post", "post_002")["main_point"] == (
        "A post main point"
    )
    with pytest.raises(KeyError, match="Unknown content type"):
        review_ui.get_content_item("image", "post_002")


def test_review_ui_generation_options_expose_type_platform_and_profiles():
    from scripts.review_ui import get_generation_options

    options = get_generation_options()

    assert any(
        item["id"] == "single_page" and item["content_kind"] == "post"
        for item in options["formats"]
    )
    assert any(
        item["id"] == "instagram_feed"
        and "single_page" in item["supported_format_ids"]
        for item in options["platforms"]
    )
    assert any(
        item["id"] == "rational_thoughts"
        and item["name"] == "Buddha's Teachings"
        for item in options["profiles"]
    )
    assert any(
        item["id"] == "default" and item["name"] == "d_agnostic_being"
        for item in options["brands"]
    )
    assert any(
        item["id"] == "life_is_a_glitch"
        and item["name"] == "Life Is a Glitch"
        for item in options["brands"]
    )
    assert options["categories"] == [{"id": "comedy", "name": "Comedy"}]
    assert len(options["comedy_subtypes"]) == 10
    assert any(
        item["id"] == "qa_engineering_ai" for item in options["profiles"]
    )
    assert len(options["qa_subtypes"]) == 8
    assert options["qa_subtype_error"] == ""
    assert any(
        item["id"] == "linkedin"
        and {"linkedin_text_post", "single_page"}.issubset(
            item["supported_format_ids"]
        )
        for item in options["platforms"]
    )
    assert any(
        item["id"] == "linkedin_text_post" and item["content_kind"] == "post"
        for item in options["formats"]
    )


def test_review_ui_keeps_existing_options_when_comedy_module_is_unavailable(
    monkeypatch,
):
    from config_loader import ConfigurationError
    from scripts import review_ui

    def fail_comedy_load():
        raise ConfigurationError("Comedy category config is invalid.")

    monkeypatch.setattr(review_ui, "load_comedy_config", fail_comedy_load)
    options = review_ui.get_generation_options()

    assert options["categories"] == []
    assert options["comedy_subtypes"] == []
    assert options["category_error"] == "Comedy category config is invalid."
    assert {item["id"] for item in options["formats"]} >= {
        "reel",
        "single_page",
        "linkedin_text_post",
    }


def test_review_ui_comedy_batch_rotates_through_subtypes(monkeypatch):
    from scripts import review_ui

    generated = []

    def fake_generate_and_save(payload):
        generated.append(payload["comedy_subtype"])
        return {"id": f"reel_{len(generated):03}", "type": "reel", "title": "Draft"}

    monkeypatch.setattr(review_ui, "generate_and_save", fake_generate_and_save)
    results = review_ui.generate_batch_and_save(
        {"category_id": "comedy", "count": 10}
    )

    assert len(results) == 10
    assert generated == [
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
    ]


def test_review_ui_qa_batch_rotates_topic_pillars(monkeypatch):
    from scripts import review_ui

    generated = []

    def fake_generate_and_save(payload):
        generated.append(payload["content_subtype"])
        return {"id": f"reel_{len(generated):03}", "type": "reel", "title": "Draft"}

    monkeypatch.setattr(review_ui, "generate_and_save", fake_generate_and_save)
    results = review_ui.generate_batch_and_save(
        {"profile_id": "qa_engineering_ai", "count": 8}
    )

    assert len(results) == 8
    assert generated == [
        "testing_strategy",
        "automation_architecture",
        "ui_api_integration_testing",
        "ci_flaky_tests",
        "exploratory_debugging",
        "ai_assisted_qa",
        "llm_testing",
        "qa_communication",
    ]


def test_review_ui_reports_partial_batch_saves(monkeypatch):
    from scripts import review_ui

    attempts = []

    def fake_generate_and_save(payload):
        attempts.append(payload)
        if len(attempts) == 2:
            raise ValueError("provider rejected the request")
        return {"id": "reel_001", "type": "reel", "title": "Draft"}

    monkeypatch.setattr(review_ui, "generate_and_save", fake_generate_and_save)

    with pytest.raises(
        review_ui.PartialGenerationError,
        match="saving 1 of 3 drafts.*remain in the library",
    ):
        review_ui.generate_batch_and_save(
            {"category_id": "comedy", "count": 3}
        )


def test_review_ui_text_post_has_no_visual_production_stage(
    tmp_path, monkeypatch
):
    from scripts import review_ui

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    posts_directory.mkdir()
    record = {
        "id": "post_001",
        "title": "Investigating flaky tests",
        "post_text": "A flaky test is a signal to investigate.",
        "status": "Approved",
        "profile_id": "qa_engineering_ai",
        "format_id": "linkedin_text_post",
        "platform_id": "linkedin",
    }
    (posts_directory / "post_001.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {"reel": tmp_path / "generated_reels", "post": posts_directory},
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", assets_directory
    )

    stages = review_ui.get_pipeline("post", "post_001")["stages"]

    assert all(stage["id"] != "design_prompt" for stage in stages)
    video = next(stage for stage in stages if stage["id"] == "video")
    assert video["status"] == "not_applicable"
    assert review_ui.list_assets("post", "post_001") == []
    assert review_ui.get_dashboard_summary()["ready_for_production"] == 1


def test_review_ui_approves_post_and_records_history(tmp_path, monkeypatch):
    from scripts import review_ui
    import post_storage

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    posts_directory.mkdir()
    assets_directory.mkdir()
    record = {
        "id": "post_001",
        "title": "A post",
        "main_point": "A main point",
        "supporting_copy": "Some supporting copy.",
        "visual_labels": "First label, Second label",
        "design_prompt": "A clean diagram.",
        "profile_id": "rational_thoughts",
        "format_id": "single_page",
        "platform_id": "instagram_feed",
        "status": "Draft",
    }
    (posts_directory / "post_001.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    monkeypatch.setattr(post_storage, "GENERATED_POSTS_DIRECTORY", posts_directory)
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {"reel": tmp_path / "generated_reels", "post": posts_directory},
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", assets_directory
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_POSTS_DIRECTORY", posts_directory
    )
    (assets_directory / "post_001_design_prompt.txt").write_text(
        "Existing prompt", encoding="utf-8"
    )

    assert review_ui.get_dashboard_summary()["ready_for_production"] == 0
    updated = review_ui.review_content("post", "post_001", "Approved")
    pipeline = review_ui.get_pipeline("post", "post_001")

    assert updated["status"] == "Approved"
    assert review_ui.get_dashboard_summary()["ready_for_production"] == 1
    assert next(
        stage for stage in pipeline["stages"] if stage["id"] == "design_prompt"
    )["status"] == "ready"
    assert review_ui.get_history("post", "post_001")[0]["decision"] == "Approved"
    with pytest.raises(ValueError, match="Only Draft content"):
        review_ui.review_content("post", "post_001", "Rejected")


def test_review_ui_reel_stage_prerequisites_assets_and_history(
    tmp_path, monkeypatch
):
    from scripts import review_ui
    import reel_storage

    reels_directory = tmp_path / "generated_reels"
    videos_directory = tmp_path / "generated_videos"
    images_directory = tmp_path / "generated_images"
    assets_directory = tmp_path / "generated_assets"
    for directory in (
        reels_directory,
        videos_directory,
        images_directory,
        assets_directory,
    ):
        directory.mkdir()
    reel = {
        "id": "reel_001",
        "title": "A reel",
        "hook": "Start here.",
        "script": "A short script.",
        "status": "Draft",
    }
    (reels_directory / "reel_001.json").write_text(
        json.dumps(reel), encoding="utf-8"
    )
    monkeypatch.setattr(reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory)
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {
            "reel": reels_directory,
            "post": tmp_path / "generated_posts",
        },
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", assets_directory
    )

    with pytest.raises(ValueError, match="require Approved"):
        review_ui.run_production_stage("reel", "reel_001", "storyboard")

    review_ui.review_content("reel", "reel_001", "Approved")
    with pytest.raises(ValueError, match="storyboard before image prompts"):
        review_ui.run_production_stage("reel", "reel_001", "image_prompts")

    def create_storyboard(reel_id):
        storyboard = videos_directory / f"{reel_id}_storyboard.json"
        scenes = videos_directory / f"{reel_id}_scenes.txt"
        storyboard.write_text('{"scenes": []}', encoding="utf-8")
        scenes.write_text("Scene one", encoding="utf-8")
        return storyboard

    monkeypatch.setattr(review_ui, "generate_storyboard", create_storyboard)
    assert review_ui.run_production_stage(
        "reel", "reel_001", "storyboard"
    ) == {"stage": "storyboard", "status": "ready"}
    pipeline = review_ui.get_pipeline("reel", "reel_001")
    statuses = {stage["id"]: stage for stage in pipeline["stages"]}
    assert statuses["storyboard"]["status"] == "ready"
    assert statuses["scene_plan"]["status"] == "ready"
    assert statuses["image_prompts"]["can_run"] is True
    assert {asset["key"] for asset in review_ui.list_assets("reel", "reel_001")} >= {
        "storyboard",
        "scene_plan",
    }
    assert review_ui.get_history("reel", "reel_001")[0]["event"] == "stage_ready"


def test_review_ui_http_review_endpoint_updates_post(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer
    import threading
    from urllib.request import Request, urlopen

    from scripts import review_ui
    import post_storage

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    posts_directory.mkdir()
    record = {
        "id": "post_001",
        "title": "HTTP review test",
        "status": "Draft",
    }
    (posts_directory / "post_001.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    monkeypatch.setattr(post_storage, "GENERATED_POSTS_DIRECTORY", posts_directory)
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {"reel": tmp_path / "generated_reels", "post": posts_directory},
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", assets_directory
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), review_ui.ReviewRequestHandler
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            f"{base_url}/api/content/post/post_001/review",
            data=json.dumps({"decision": "Approved"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        assert result["record"]["status"] == "Approved"
        assert json.loads(
            (posts_directory / "post_001.json").read_text(encoding="utf-8")
        )["status"] == "Approved"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_review_ui_asset_endpoint_returns_text_for_inline_copy(
    tmp_path, monkeypatch
):
    from http.server import ThreadingHTTPServer
    import threading
    from urllib.request import urlopen

    from scripts import review_ui

    posts_directory = tmp_path / "generated_posts"
    assets_directory = tmp_path / "generated_assets"
    posts_directory.mkdir()
    assets_directory.mkdir()
    (posts_directory / "post_001.json").write_text(
        json.dumps(
            {
                "id": "post_001",
                "title": "A post",
                "status": "Approved",
            }
        ),
        encoding="utf-8",
    )
    (assets_directory / "post_001_design_prompt.txt").write_text(
        "Exact prompt text\nwith multiple lines.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        review_ui,
        "_CONTENT_DIRECTORIES",
        {"reel": tmp_path / "generated_reels", "post": posts_directory},
    )
    monkeypatch.setattr(
        review_ui, "GENERATED_ASSETS_DIRECTORY", assets_directory
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), review_ui.ReviewRequestHandler
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}"
            "/api/assets/post/post_001/design_prompt",
            timeout=5,
        ) as response:
            payload = json.loads(response.read())
            assert response.headers.get_content_type() == "application/json"
        assert payload == {
            "name": "post_001_design_prompt.txt",
            "type": "Image prompt",
            "content": "Exact prompt text\nwith multiple lines.",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ready_design_prompt_includes_exact_diagram_labels(tmp_path):
    from config_loader import load_format, load_platform
    from post_prompt import build_ready_design_prompt

    prompt = build_ready_design_prompt(
        {
            "title": "Correlation isn't causation",
            "main_point": "A third factor may explain both.",
            "supporting_copy": "Look for a plausible confounder.",
            "visual_labels": (
                "Warm weather\n"
                "Higher ice-cream sales\n"
                "More time swimming"
            ),
            "design_prompt": (
                "Draw warm weather as the shared cause and label each node."
            ),
        },
        load_format("single_page"),
        load_platform("instagram_feed"),
    )

    assert "EXACT DIAGRAM LABELS TO INCLUDE:" in prompt
    assert "Warm weather\nHigher ice-cream sales\nMore time swimming" in prompt
    assert "Label every diagram node clearly" in prompt


def test_ready_design_prompt_omits_empty_diagram_label_section():
    from config_loader import load_format, load_platform
    from post_prompt import build_ready_design_prompt

    prompt = build_ready_design_prompt(
        {
            "title": "Think clearly",
            "main_point": "Ask what would change your mind.",
            "supporting_copy": "Evidence matters more than confidence.",
            "visual_labels": "None",
            "design_prompt": "Minimal editorial typography.",
        },
        load_format("single_page"),
        load_platform("instagram_feed"),
    )

    assert "EXACT DIAGRAM LABELS TO INCLUDE:" not in prompt


def test_main_rejects_empty_generation_brief():
    from scripts import main

    with pytest.raises(SystemExit) as error:
        main.main(["--brief", "  "])
    assert error.value.code == 2


def test_scene_generator_compatibility_command_writes_storyboard(
    tmp_path, monkeypatch
):
    from scripts import scene_generator, storyboard_generator

    reels_directory = tmp_path / "project" / "generated_reels"
    videos_directory = tmp_path / "project" / "generated_videos"
    reels_directory.mkdir(parents=True)
    (reels_directory / "reel_001.json").write_text(
        json.dumps(
            {
                "id": "reel_001",
                "hook": "Think again.",
                "script": "We can win. (Visual: A city street.) Then move.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        scene_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        storyboard_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["scene_generator.py", "reel_001"])

    assert scene_generator.main() == 0

    scene_text = (videos_directory / "reel_001_scenes.txt").read_text(
        encoding="utf-8"
    )
    assert "Think again." in scene_text
    assert "We can win." in scene_text
    assert "Then move." in scene_text
    assert "A city street" in scene_text
    assert "NARRATION: We can win." in scene_text
    assert "VISUAL: A city street." in scene_text
    assert "NARRATION: Then move." in scene_text
    assert "UNTIMED" in scene_text
    assert (videos_directory / "reel_001_storyboard.json").is_file()


def test_storyboard_preserves_reel_018_timed_beats_and_content(
    tmp_path, monkeypatch
):
    from scripts import storyboard_generator

    reels_directory = tmp_path / "generated_reels"
    videos_directory = tmp_path / "generated_videos"
    reels_directory.mkdir()
    (reels_directory / "reel_018.json").write_text(
        (FIXTURES_DIRECTORY / "reel_018.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        storyboard_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )

    storyboard_file = storyboard_generator.generate_storyboard("reel_018")
    storyboard = storyboard_generator.read_storyboard(storyboard_file)

    assert storyboard.duration_seconds == 30
    assert [
        (scene.start_seconds, scene.end_seconds)
        for scene in storyboard.scenes
    ] == [(0, 5), (5, 12), (12, 20), (20, 27), (27, 30)]
    assert len(storyboard.scenes) == 5
    assert "nodding seriously" in storyboard.scenes[0].visual_beats[0]
    assert storyboard.scenes[0].narration == (
        "Yes, I completely agree. The Q3 projections are looking very promising.",
    )
    assert "batting at Alex’s ear" in storyboard.scenes[1].visual_beats[0]
    assert "asdfghjkl" in storyboard.scenes[2].sound_cues[0]
    assert "Meeting adjourned." in storyboard.scenes[4].narration[0]

    scenes_text = (videos_directory / "reel_018_scenes.txt").read_text(
        encoding="utf-8"
    )
    assert scenes_text.count("SCENE S") == 5
    assert "TOTAL DURATION: 0:30" in scenes_text
    assert "NARRATION: Yes, I completely agree." in scenes_text


@pytest.mark.parametrize(
    "script",
    [
        "(0:00-0:05) First beat.\n\n(0:04-0:08) Overlap.",
        "(0:08-0:05) Reversed time.",
        "(0:99-1:05) Invalid seconds.",
        "(0:00-) Missing end time.",
    ],
)
def test_storyboard_rejects_invalid_timing(script):
    from scripts.storyboard_generator import (
        StoryboardValidationError,
        build_storyboard,
    )

    with pytest.raises(StoryboardValidationError):
        build_storyboard({"hook": "Hook", "script": script})


def test_storyboard_keeps_untimed_legacy_scenes_untimed():
    from scripts.storyboard_generator import build_storyboard, render_storyboard

    storyboard = build_storyboard(
        {
            "hook": "A short opening.",
            "script": "First paragraph.\n\nSecond paragraph.",
        }
    )

    assert storyboard.duration_seconds is None
    assert len(storyboard.scenes) == 2
    assert all(scene.start_seconds is None for scene in storyboard.scenes)
    rendered = render_storyboard(storyboard)
    assert rendered.count("| UNTIMED") == 2
    assert "First paragraph." in rendered


def test_storyboard_extracts_explicit_transition_and_continuity():
    from scripts.storyboard_generator import build_storyboard

    storyboard = build_storyboard(
        {
            "script": (
                "(0:00-0:05) Visual: Alex enters the office. "
                "Transition: Cut to the desk. "
                "Continuity: Keep the navy blazer and glasses."
            )
        }
    )

    scene = storyboard.scenes[0]
    assert scene.visual_beats == ("Alex enters the office.",)
    assert scene.transition == "Cut to the desk."
    assert scene.continuity == ("Keep the navy blazer and glasses.",)


def test_master_prompt_uses_storyboard_timing_and_separates_visuals(
    tmp_path, monkeypatch
):
    from scripts import storyboard_generator, video_prompt_generator

    reels_directory = tmp_path / "generated_reels"
    videos_directory = tmp_path / "generated_videos"
    images_directory = tmp_path / "generated_images"
    reels_directory.mkdir()
    images_directory.mkdir()
    (reels_directory / "reel_018.json").write_text(
        (FIXTURES_DIRECTORY / "reel_018.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (images_directory / "reel_018_image_prompts.txt").write_text(
        "SCENE S01 | 0:00-0:05: image prompt", encoding="utf-8"
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        storyboard_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )

    storyboard_generator.generate_storyboard("reel_018")
    prompt_file = video_prompt_generator.generate_master_prompt("reel_018")
    master_prompt = prompt_file.read_text(encoding="utf-8")
    voiceover = master_prompt.split("Voiceover/dialogue:\n", 1)[1].split(
        "Timing and production cues:", 1
    )[0]

    assert "[0:00-0:05] Yes, I completely agree." in voiceover
    assert "Meeting adjourned." in voiceover
    assert "[Medium shot]" not in voiceover
    assert "nodding seriously" not in voiceover
    assert "Timing and production cues:" in master_prompt
    assert "CAMERA:" in master_prompt
    assert "SFX:" in master_prompt
    assert "asdfghjkl" in master_prompt
    assert master_prompt.count("SCENE S01 | 0:00-0:05: image prompt") == 1
    assert "Visual storyboard:" not in master_prompt
    assert "SCENE S01 | 0:00-0:05: image prompt" in master_prompt


def test_master_prompt_timing_cues_keep_storyboard_continuity():
    from scripts.storyboard_generator import build_storyboard
    from scripts.video_prompt_generator import _render_timing_cues

    storyboard = build_storyboard(
        {
            "script": (
                "(0:00-0:05) Visual: Alex enters. "
                "Continuity: Keep the blue jacket. "
                "Transition: Cut to the door."
            )
        }
    )

    cues = _render_timing_cues(storyboard)

    assert "CONTINUITY: Keep the blue jacket." in cues
    assert "CUT: Cut to the door." in cues


def test_comedy_master_video_prompt_uses_comedy_duration_and_timing_guidance(
    tmp_path, monkeypatch
):
    from scripts import video_prompt_generator

    videos_directory = tmp_path / "generated_videos"
    images_directory = tmp_path / "generated_images"
    videos_directory.mkdir()
    images_directory.mkdir()
    (images_directory / "reel_001_image_prompts.txt").write_text(
        "SCENE S01 | UNTIMED: A person celebrates cancelled plans.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        video_prompt_generator,
        "load_reel",
        lambda reel_id: {
            "id": reel_id,
            "title": "Cancelled plans",
            "hook": "Plans cancelled.",
            "script": "A person celebrates.",
            "profile_id": "comedy",
            "format_id": "reel",
            "platform_id": "instagram",
            "category_id": "comedy",
            "comedy_subtype": "pov",
        },
    )

    prompt_file = video_prompt_generator.generate_master_prompt("reel_001")
    prompt = prompt_file.read_text(encoding="utf-8")

    assert "Recommended duration: 8-20 seconds" in prompt
    assert "Comedy: Selected subtype: POV Comedy" in prompt
    assert "time reactions and pauses for the punchline" in prompt


def test_comedy_image_prompt_chooses_visual_approach_for_the_joke(
    tmp_path, monkeypatch
):
    from scripts import image_prompt_generator

    videos_directory = tmp_path / "generated_videos"
    images_directory = tmp_path / "generated_images"
    videos_directory.mkdir()
    images_directory.mkdir()
    (videos_directory / "reel_001_storyboard.json").write_text(
        "{}", encoding="utf-8"
    )
    monkeypatch.setattr(
        image_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        image_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        image_prompt_generator,
        "load_reel",
        lambda reel_id: {
            "id": reel_id,
            "hook": "My alarm says good morning.",
            "script": "I disagree.",
            "profile_id": "comedy",
            "format_id": "reel",
            "platform_id": "instagram",
            "category_id": "comedy",
            "comedy_subtype": "objects_with_personalities",
        },
    )
    monkeypatch.setattr(
        image_prompt_generator, "read_storyboard", lambda path: object()
    )
    monkeypatch.setattr(
        image_prompt_generator,
        "render_storyboard",
        lambda storyboard: "SCENE S01 | 0:00-0:05\nVisual: A person reacts.",
    )
    model = Mock()
    model.generate_reel.return_value = "Image prompts"

    image_prompt_generator.generate_image_prompts("reel_001", ai_service=model)

    prompt = model.generate_reel.call_args.args[0]
    assert "Objects With Personalities" in prompt
    assert "one concise paragraph of at most 60 words" in prompt
    assert "preserving its exact ID/time" in prompt
    assert "SCENE S01 | 0:00-0:05" in prompt
    assert "Supported approaches:" not in prompt


def test_image_prompts_save_in_generated_images_and_video_reads_them(
    tmp_path, monkeypatch
):
    from scripts import (
        image_prompt_generator,
        storyboard_generator,
        video_prompt_generator,
    )

    videos_directory = tmp_path / "project" / "generated_videos"
    images_directory = tmp_path / "project" / "generated_images"
    reels_directory = tmp_path / "project" / "generated_reels"
    videos_directory.mkdir(parents=True)
    reels_directory.mkdir(parents=True)
    (videos_directory / "reel_001_scenes.txt").write_text(
        "SCENE 1\nA short scene.", encoding="utf-8"
    )
    (reels_directory / "reel_001.json").write_text(
        json.dumps(
            {
                "id": "reel_001",
                "profile_id": "comedy",
                "format_id": "reel",
                "platform_id": "instagram",
                "title": "Example",
                "hook": "A hook",
                "script": "A line.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        image_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        storyboard_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(
        image_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(sys, "argv", ["image_prompt_generator.py", "reel_001"])
    model = Mock()
    model.generate_reel.return_value = "Storyboard prompts"
    monkeypatch.setattr(
        image_prompt_generator, "AIService", lambda: model
    )

    assert image_prompt_generator.main() == 0
    prompt_file = images_directory / "reel_001_image_prompts.txt"
    assert prompt_file.read_text(encoding="utf-8") == "Storyboard prompts"
    generation_prompt = model.generate_reel.call_args.args[0]
    assert "one concise paragraph of at most 60 words" in generation_prompt
    assert "Relatable everyday environments" in generation_prompt
    assert "Instagram Reel" in generation_prompt
    assert "Aspect ratio: 9:16" in generation_prompt

    monkeypatch.setattr(sys, "argv", ["video_prompt_generator.py", "reel_001"])
    assert video_prompt_generator.main() == 0
    master_prompt = (
        videos_directory / "reel_001_master_prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Storyboard prompts" in master_prompt
    assert "A line." in master_prompt
    assert "Energetic but readable camera movement" in master_prompt
    assert "modern Indian corporate environment" not in master_prompt


def test_prepare_reel_runs_storyboard_preparation_stages(monkeypatch):
    from scripts import prepare_reel

    stages = []
    monkeypatch.setattr(
        prepare_reel, "generate_storyboard", lambda reel_id: stages.append(
            ("storyboard", reel_id)
        ) or "scenes.txt"
    )
    monkeypatch.setattr(
        prepare_reel, "generate_image_prompts", lambda reel_id: stages.append(
            ("images", reel_id)
        ) or "images.txt"
    )
    monkeypatch.setattr(
        prepare_reel, "generate_master_prompt", lambda reel_id: stages.append(
            ("video", reel_id)
        ) or "video.txt"
    )

    assert prepare_reel.main(["reel_007"]) == 0
    assert stages == [
        ("storyboard", "reel_007"),
        ("images", "reel_007"),
        ("video", "reel_007"),
    ]


def test_prepare_reel_stops_when_a_stage_fails(monkeypatch):
    from scripts import prepare_reel

    monkeypatch.setattr(
        prepare_reel, "generate_storyboard", lambda reel_id: "storyboard.json"
    )

    def fail_image_stage(reel_id):
        raise AIServiceError("model unavailable")

    monkeypatch.setattr(
        prepare_reel, "generate_image_prompts", fail_image_stage
    )
    monkeypatch.setattr(
        prepare_reel,
        "generate_master_prompt",
        lambda reel_id: pytest.fail("Video stage must not run."),
    )

    assert prepare_reel.main(["reel_007"]) == 1


def test_video_prompt_generator_reads_legacy_image_prompt_path(
    tmp_path, monkeypatch
):
    from scripts import video_prompt_generator

    videos_directory = tmp_path / "generated_videos"
    images_directory = tmp_path / "generated_images"
    reels_directory = tmp_path / "generated_reels"
    videos_directory.mkdir()
    reels_directory.mkdir()
    (videos_directory / "reel_002_image_prompts.txt").write_text(
        "Legacy storyboard", encoding="utf-8"
    )
    (reels_directory / "reel_002.json").write_text(
        json.dumps({"id": "reel_002"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        reel_storage, "GENERATED_REELS_DIRECTORY", reels_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_IMAGES_DIRECTORY", images_directory
    )
    monkeypatch.setattr(
        video_prompt_generator, "GENERATED_VIDEOS_DIRECTORY", videos_directory
    )
    monkeypatch.setattr(sys, "argv", ["video_prompt_generator.py", "reel_002"])

    assert video_prompt_generator.main() == 0
    prompt = (
        videos_directory / "reel_002_master_prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Legacy storyboard" in prompt
