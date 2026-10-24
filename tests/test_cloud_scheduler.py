from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from cloud_scheduler import CloudScheduler, CloudSchedulerError
from scripts import review_ui


@pytest.fixture
def post(tmp_path, monkeypatch):
    posts = tmp_path / "posts"
    posts.mkdir()
    (posts / "post_001.json").write_text("{}")
    monkeypatch.setitem(review_ui._CONTENT_DIRECTORIES, "post", posts)
    store = {"post_001": {"format_id": "image_reel", "platform_id": "instagram", "status": "Approved",
                          "caption": "Hook\n\nTeaching: SN 36.6\n\nWhich arrow?\n\n#Buddhism",
                          "scheduled_at": "2030-01-01T14:00:00+00:00"}}
    monkeypatch.setattr(review_ui, "load_post", lambda cid: dict(store[cid]))
    monkeypatch.setattr(review_ui, "save_post", lambda cid, rec: store.__setitem__(cid, dict(rec)))
    monkeypatch.setattr(review_ui, "_append_history", lambda *a, **k: None)
    video, cover = tmp_path / "reel.mp4", tmp_path / "cover.jpg"
    video.write_bytes(b"mp4")
    cover.write_bytes(b"jpg")
    monkeypatch.setattr(review_ui, "reel_video_path", lambda cid: video)
    monkeypatch.setattr(review_ui, "post_image_path", lambda cid: cover)
    monkeypatch.setattr(review_ui, "facebook_auto_enabled", lambda: False)
    monkeypatch.setattr(review_ui, "threads_configured", lambda: True)
    return store


def test_queue_uploads_media_and_sends_the_job(post):
    host = Mock()
    host.upload.side_effect = [("k1", "https://cdn/v.mp4"), ("k2", "https://cdn/c.jpg")]
    cloud = Mock()
    job = review_ui.queue_cloud_job("post_001", host=host, cloud=cloud)
    assert cloud.put_job.call_args.args[0] == "post_001"
    assert job["kind"] == "reel" and job["media"] == {"video_url": "https://cdn/v.mp4", "cover_url": "https://cdn/c.jpg"}
    assert job["platforms"] == {"instagram": True, "facebook": False, "threads": True}
    assert job["first_comment"] == "Teaching: SN 36.6\n\nWhich arrow?" and job["r2_keys"] == ["k1", "k2"]
    assert post["post_001"]["cloud_job"]["keys"] == ["k1", "k2"]

    # Re-queuing (new caption or render) replaces the upload and removes the old files.
    host.upload.side_effect = [("k3", "u3"), ("k4", "u4")]
    review_ui.queue_cloud_job("post_001", host=host, cloud=cloud)
    assert [call.args[0] for call in host.delete.call_args_list] == ["k1", "k2"]


def test_failed_queue_removes_its_uploads(post):
    host = Mock()
    host.upload.side_effect = [("k1", "u1"), ("k2", "u2")]
    cloud = Mock()
    cloud.put_job.side_effect = CloudSchedulerError("Could not reach the cloud scheduler")
    with pytest.raises(CloudSchedulerError):
        review_ui.queue_cloud_job("post_001", host=host, cloud=cloud)
    assert [call.args[0] for call in host.delete.call_args_list] == ["k1", "k2"]
    assert "cloud_job" not in post["post_001"]


def test_sync_records_results_and_clears_the_cloud_job(post):
    post["post_001"]["cloud_job"] = {"keys": ["k1"]}
    cloud = Mock()
    cloud.get_jobs.return_value = [{
        "id": "post_001", "status": "done", "comment_id": "c9",
        "ig": {"media_id": "m1", "permalink": "https://instagram/p/1", "published_at": "2030-01-01T14:00:30Z"},
        "threads": {"media_id": "t1", "permalink": "https://threads/t1"},
        "errors": {"facebook": "Facebook returned HTTP 400: We limit how often you can post"},
    }]
    results = review_ui.sync_cloud_jobs(cloud=cloud)
    record = post["post_001"]
    assert results == [("post_001", "published", "https://instagram/p/1")]
    assert record["status"] == "Published" and record["instagram_media_id"] == "m1"
    assert record["threads_media_id"] == "t1" and record["instagram_comment_id"] == "c9"
    assert record["facebook_error"].startswith("Facebook returned") and "cloud_job" not in record
    assert "scheduled_at" not in record
    cloud.delete_job.assert_called_once_with("post_001")


def test_local_scheduler_leaves_cloud_jobs_alone_unless_the_cloud_is_lost(post, monkeypatch):
    now = datetime(2030, 1, 1, 14, 30, tzinfo=timezone.utc)
    post["post_001"].update(scheduled_at=(now - timedelta(minutes=5)).isoformat(), cloud_job={"keys": []})
    published = []
    monkeypatch.setattr(review_ui, "publish_content", lambda *a, **k: published.append(1) or {})
    assert review_ui.publish_due_posts(now=now) == []  # within 20 minutes: the cloud's turn

    post["post_001"]["scheduled_at"] = (now - timedelta(minutes=30)).isoformat()
    queued = Mock()
    queued.get_jobs.return_value = [{"id": "post_001", "status": "queued"}]
    monkeypatch.setattr(review_ui, "CloudScheduler", lambda: queued)
    assert review_ui.publish_due_posts(now=now) == [] and published == []  # cloud still on it

    lost = Mock()
    lost.get_jobs.side_effect = CloudSchedulerError("unreachable")
    monkeypatch.setattr(review_ui, "CloudScheduler", lambda: lost)
    publisher = Mock()
    publisher.recent_media.return_value = []
    review_ui.publish_due_posts(now=now, publisher=publisher)
    assert published == [1]  # Mac takes over after checking Instagram for a copy
    publisher.recent_media.assert_called_once()


def test_client_sends_the_secret_and_reports_errors():
    session = Mock()
    session.request.return_value = Mock(status_code=401, json=lambda: {"error": "unauthorised"})
    client = CloudScheduler(url="https://worker.example", secret="s3cret", session=session)
    with pytest.raises(CloudSchedulerError, match="401"):
        client.health()
    assert session.request.call_args.kwargs["headers"] == {"Authorization": "Bearer s3cret"}
