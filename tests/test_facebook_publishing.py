from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

from facebook_publisher import FacebookPublishError, FacebookPublisher
from scripts import review_ui


def _response(payload, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    return response


def _publisher(responses):
    session = Mock()
    session.request.side_effect = responses
    return FacebookPublisher("PAGE", "TOKEN", session=session, sleep=lambda s: None), session


def test_publish_reel_runs_start_upload_finish_then_returns_link(tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"mp4data")
    publisher, session = _publisher([
        _response({"video_id": "V1", "upload_url": "https://rupload.example/V1"}),
        _response({"success": True}),
        _response({"success": True}),
        _response({"status": {"video_status": "processing", "publishing_phase": {"status": "in_progress"}}}),
        _response({"status": {"video_status": "ready", "publishing_phase": {"status": "complete"}}}),
        _response({"permalink_url": "/reel/V1"}),
    ])
    result = publisher.publish_reel(video, "Hook line #Buddhism")
    assert result == {"video_id": "V1", "permalink": "https://www.facebook.com/reel/V1"}
    calls = session.request.call_args_list
    assert calls[0].kwargs["data"]["upload_phase"] == "start"
    upload = calls[1]
    assert upload.args[1] == "https://rupload.example/V1"
    assert upload.kwargs["headers"]["Authorization"] == "OAuth TOKEN"
    assert upload.kwargs["headers"]["file_size"] == "7" and upload.kwargs["data"] == b"mp4data"
    finish = calls[2].kwargs["data"]
    assert finish["upload_phase"] == "finish" and finish["video_state"] == "PUBLISHED"
    assert finish["description"] == "Hook line #Buddhism"


def test_network_errors_are_transient_and_rejections_are_not(tmp_path):
    publisher, _ = _publisher([requests.ConnectionError("down")])
    with pytest.raises(FacebookPublishError) as error:
        publisher.page_info()
    assert error.value.transient and "TOKEN" not in str(error.value)
    publisher, _ = _publisher([_response({"error": {"message": "Invalid token"}}, 400)])
    with pytest.raises(FacebookPublishError) as error:
        publisher.page_info()
    assert not error.value.transient and "Invalid token" in str(error.value)


@pytest.fixture
def reel(tmp_path, monkeypatch):
    posts = tmp_path / "posts"
    posts.mkdir()
    (posts / "post_001.json").write_text("{}")
    monkeypatch.setitem(review_ui._CONTENT_DIRECTORIES, "post", posts)
    monkeypatch.setattr(review_ui, "facebook_configured", lambda: True)
    store = {}
    monkeypatch.setattr(review_ui, "load_post", lambda cid: dict(store[cid]))
    monkeypatch.setattr(review_ui, "save_post", lambda cid, rec: store.__setitem__(cid, dict(rec)))
    monkeypatch.setattr(review_ui, "_append_history", lambda *a, **k: None)
    video = tmp_path / "post_001_reel.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(review_ui, "reel_video_path", lambda cid: video)
    store["post_001"] = {"format_id": "image_reel", "status": "Published",
                         "caption": "Hook **line**\n\n#Buddhism"}
    return store


def test_post_to_facebook_saves_link_and_retries_network_failures(reel):
    publisher = Mock()
    publisher.publish_reel.side_effect = FacebookPublishError("Could not reach Facebook.", transient=True)
    now = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(FacebookPublishError):
        review_ui.post_to_facebook("post_001", publisher=publisher, now=now)
    record = reel["post_001"]
    assert record["facebook_attempts"] == 1
    assert record["facebook_retry_at"] == (now + timedelta(minutes=5)).isoformat()

    publisher.publish_reel.side_effect = None
    publisher.publish_reel.return_value = {"video_id": "V9", "permalink": "https://fb/reel/V9"}
    monkey_now = now + timedelta(minutes=6)
    assert review_ui.retry_facebook_posts(now=now + timedelta(minutes=2), publisher=publisher) == []
    outcome = review_ui.retry_facebook_posts(now=monkey_now, publisher=publisher)
    assert outcome[0][1] == "facebook published"
    record = reel["post_001"]
    assert record["facebook_video_id"] == "V9" and "facebook_error" not in record
    assert publisher.publish_reel.call_args.args[1] == "Hook line\n\n#Buddhism"  # no ** marks
    with pytest.raises(ValueError, match="already on Facebook"):
        review_ui.post_to_facebook("post_001", publisher=publisher)
