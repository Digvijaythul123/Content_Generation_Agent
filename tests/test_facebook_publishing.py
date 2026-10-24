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
    monkeypatch.setattr(review_ui, "facebook_auto_enabled", lambda: True)
    monkeypatch.setattr(review_ui, "threads_configured", lambda: False)
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


def test_photo_and_multi_photo_posts(tmp_path):
    one, two = tmp_path / "s1.jpg", tmp_path / "s2.jpg"
    one.write_bytes(b"a")
    two.write_bytes(b"b")
    publisher, session = _publisher([
        _response({"id": "P1", "post_id": "PAGE_P1"}),
        _response({"permalink_url": "https://fb/p/1"}),
    ])
    assert publisher.publish_photo(one, "cap") == {"post_id": "PAGE_P1", "permalink": "https://fb/p/1"}
    upload = session.request.call_args_list[0]
    assert upload.kwargs["files"]["source"][1] == b"a" and upload.kwargs["data"]["message"] == "cap"

    publisher, session = _publisher([
        _response({"id": "M1"}), _response({"id": "M2"}),
        _response({"id": "PAGE_POST"}), _response({"permalink_url": "https://fb/p/2"}),
    ])
    result = publisher.publish_photos([one, two], "carousel caption")
    assert result == {"post_id": "PAGE_POST", "permalink": "https://fb/p/2"}
    calls = session.request.call_args_list
    assert calls[0].kwargs["data"]["published"] == "false"
    feed = calls[2].kwargs["data"]
    assert feed["message"] == "carousel caption"
    assert feed["attached_media[0]"] == '{"media_fbid": "M1"}' and feed["attached_media[1]"] == '{"media_fbid": "M2"}'


def test_feed_posts_go_to_facebook_and_can_be_scheduled(reel, tmp_path, monkeypatch):
    import media_renderer
    reel["post_001"] = {"format_id": "carousel", "platform_id": "instagram_feed", "status": "Published",
                        "caption": "Hook\n\n#Buddhism", "slide_count": 2}
    for number in (1, 2):
        path = tmp_path / f"slide{number}.jpg"
        path.write_bytes(b"x")
    monkeypatch.setattr(review_ui, "carousel_slide_path", lambda cid, n: tmp_path / f"slide{n}.jpg")
    publisher = Mock()
    publisher.publish_photos.return_value = {"post_id": "PP", "permalink": "https://fb/pp"}
    review_ui.post_to_facebook("post_001", publisher=publisher)
    assert [p.name for p in publisher.publish_photos.call_args.args[0]] == ["slide1.jpg", "slide2.jpg"]
    assert reel["post_001"]["facebook_post_id"] == "PP"
    with pytest.raises(ValueError, match="already on Facebook"):
        review_ui.post_to_facebook("post_001", publisher=publisher)


def test_posting_too_often_is_retried_hours_later(reel):
    publisher, _ = _publisher([_response({"error": {
        "code": 368, "message": "We limit how often you can post, comment or do other things"}}, 400)])
    with pytest.raises(FacebookPublishError) as error:
        publisher.page_info()
    assert error.value.rate_limited and error.value.transient

    failing = Mock()
    failing.publish_reel.side_effect = FacebookPublishError("We limit how often you can post", rate_limited=True)
    now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(FacebookPublishError):
        review_ui.post_to_facebook("post_001", publisher=failing, now=now)
    assert reel["post_001"]["facebook_retry_at"] == (now + timedelta(minutes=60)).isoformat()


def test_threads_posts_upload_publish_and_clean_up(reel, tmp_path, monkeypatch):
    from threads_publisher import ThreadsPublishError, ThreadsPublisher
    # The client: container, wait, publish, link.
    session = Mock()
    session.post.side_effect = [_response({"id": "C1"}), _response({"id": "T1"})]
    session.get.side_effect = [_response({"status": "FINISHED"}), _response({"permalink": "https://threads/p/1"})]
    client = ThreadsPublisher("TOKEN", "U1", session=session, sleep=lambda s: None)
    assert client.publish_video("https://cdn/v.mp4", "Hook") == {"media_id": "T1", "permalink": "https://threads/p/1"}
    first = session.post.call_args_list[0].kwargs["data"]
    assert first["media_type"] == "VIDEO" and first["video_url"] == "https://cdn/v.mp4" and first["text"] == "Hook"
    assert session.post.call_args_list[1].kwargs["data"]["creation_id"] == "C1"

    # The app: uploads the Reel, posts it, deletes the public copy.
    host = Mock()
    host.upload.return_value = ("k1", "https://cdn/reel.mp4")
    threads = Mock()
    threads.publish_video.return_value = {"media_id": "T9", "permalink": "https://threads/p/9"}
    review_ui.post_to_threads("post_001", publisher=threads, host=host)
    assert threads.publish_video.call_args.args == ("https://cdn/reel.mp4", "Hook line\n\n#Buddhism")
    host.delete.assert_called_once_with("k1")
    assert reel["post_001"]["threads_media_id"] == "T9"
    with pytest.raises(ValueError, match="already on Threads"):
        review_ui.post_to_threads("post_001", publisher=threads, host=host)

    # A network failure keeps the copy cleaned up and schedules a retry.
    reel["post_001"].pop("threads_media_id")
    threads.publish_video.side_effect = ThreadsPublishError("Could not reach Threads.", transient=True)
    now = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(ThreadsPublishError):
        review_ui.post_to_threads("post_001", publisher=threads, host=host, now=now)
    assert reel["post_001"]["threads_retry_at"] == (now + timedelta(minutes=5)).isoformat()
    assert host.delete.call_count == 2


def test_facebook_auto_posting_can_be_paused(monkeypatch):
    import facebook_publisher
    monkeypatch.setattr(facebook_publisher, "facebook_configured", lambda: True)
    monkeypatch.setattr(facebook_publisher, "get_setting", lambda name, default=None: "off")
    assert facebook_publisher.facebook_auto_enabled() is False
    monkeypatch.setattr(facebook_publisher, "get_setting", lambda name, default=None: default)
    assert facebook_publisher.facebook_auto_enabled() is True
