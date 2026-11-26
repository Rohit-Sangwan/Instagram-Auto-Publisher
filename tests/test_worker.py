import json
import time
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import httpx
import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import select

from app.assets import MediaError, allowed_url, fetch, run, stage
from app.db import MEDIA, Account, Asset, Download, Mapping, Media, Publish, Published, Schedule, Session, Settings, Source
from app.meta import BASIC, PUBLISH, Instagram, MetaError
from app.security import cipher
from app.worker import cleanup, download, eligible, next_slot, publish, recover, sync, token


@pytest.fixture(scope="module", autouse=True)
def database():
    command.upgrade(Config("alembic.ini"), "head")
    with Session.begin() as db:
        if not db.get(Settings, 1):
            db.add_all([Settings(id=1), Schedule(id=1)])


def account(identifier, expires=None):
    return Account(ig_id=str(identifier), username=f"test{identifier}",
                   expires=expires if expires is not None else time.time() + 86400,
                   scopes=[BASIC, PUBLISH], token=cipher().encrypt(b"mock-token").decode())


def test_pagination_and_discovery(monkeypatch):
    calls = []

    def mock(request):
        assert request.headers["Authorization"] == "Bearer mock-token"
        assert request.url.host == "graph.instagram.com"
        calls.append(str(request.url))
        after = request.url.params.get("after")
        data = [{"id": "513" if after else "514", "media_type": "IMAGE",
                 "timestamp": "2026-11-12T13:00:00+0000" if after else "2026-11-12T14:00:00+0000"}]
        return httpx.Response(200, json={"data": data, "paging": {} if after else {
            "next": "https://do-not-follow.example/", "cursors": {"after": "next-page"}}})

    def api(client=None):
        return Instagram(client or httpx.Client(transport=httpx.MockTransport(mock)))

    monkeypatch.setattr("app.worker.Instagram", api)
    with Session.begin() as db:
        origin, target = account(51), account(52)
        db.add_all([origin, target])
        db.flush()
        source = Source(username=origin.username, account_id=origin.id, kinds=["IMAGE"])
        db.add(source)
        db.flush()
        db.add(Mapping(source_id=source.id, account_id=target.id))
        source_id = source.id
    sync(source_id)
    sync(source_id)
    assert "after=next-page" in calls[1]
    with Session() as db:
        items = list(db.scalars(select(Media).where(Media.source_id == source_id).order_by(Media.id)))
        assert [item.ig_id for item in items] == ["513", "514"]
        jobs = list(db.scalars(select(Publish).where(Publish.media_id.in_([item.id for item in items]))))
        assert len(jobs) == 2


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "https://instagram.com/a",
                                "https://fbcdn.net.evil.invalid/a", "https://evil@fbcdn.net/a",
                                "https://fbcdn.net:8443/a"])
def test_download_rejects_untrusted_origins(url):
    assert not allowed_url(url)


def test_download_integrity(tmp_path):
    url = "https://scontent.cdninstagram.com/file"
    file = tmp_path / "bounded"

    def download(content, length, maximum):
        mock = httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"Content-Type": "image/jpeg", "Content-Length": str(length)}, content=content))
        fetch(url, file, maximum, lambda value: None, httpx.Client(transport=mock))

    download(b"abc", 3, 8)
    assert file.read_bytes() == b"abc"
    with pytest.raises(MediaError, match="Incomplete"):
        download(b"abc", 4, 8)
    with pytest.raises(MediaError, match="size limit"):
        download(b"abc", 4, 2)


def test_download_refetches_expired_urls_and_stages_assets(monkeypatch):
    url_requests = []
    png = BytesIO()
    Image.new("RGB", (400, 400), "blue").save(png, format="PNG")

    def graph(request):
        revision = "fresh" if url_requests else "expired"
        url_requests.append(revision)
        return httpx.Response(200, json={"id": "5017", "media_type": "IMAGE",
                                         "media_url": f"https://scontent.cdninstagram.com/{revision}"})

    def cdn(request):
        if request.url.path == "/expired":
            return httpx.Response(403)
        return httpx.Response(200, content=png.getvalue(), headers={"Content-Type": "image/png"})

    def api(client=None):
        return Instagram(client or httpx.Client(transport=httpx.MockTransport(graph)))

    def download_url(url, target, limit, progress):
        fetch(url, target, limit, progress, httpx.Client(transport=httpx.MockTransport(cdn)))

    monkeypatch.setattr("app.worker.Instagram", api)
    monkeypatch.setattr("app.worker.fetch", download_url)
    with Session.begin() as db:
        origin, target = account(501), account(502)
        db.add_all([origin, target])
        db.flush()
        source = Source(username=origin.username, account_id=origin.id, kinds=["IMAGE"])
        db.add(source)
        db.flush()
        media = Media(ig_id="5017", source_id=source.id, kind="IMAGE", timestamp=time.time())
        db.add(media)
        db.flush()
        download_job, publish_job = Download(media_id=media.id), Publish(media_id=media.id, account_id=target.id)
        db.add_all([download_job, publish_job])
        db.flush()
        download_id, publish_id, media_id = download_job.id, publish_job.id, media.id
    download(download_id)
    with Session() as db:
        job = db.get(Download, download_id)
        assert job.state == "pending" and job.attempts == 1 and job.next_run > time.time()
    download(download_id)
    with Session() as db:
        assert db.get(Download, download_id).state == "downloaded"
        assert db.get(Publish, publish_id).state == "ready"
        asset = db.scalar(select(Asset).where(Asset.media_id == media_id))
        assert (MEDIA / asset.filename).is_file() and asset.mime == "image/jpeg"
    assert url_requests == ["expired", "fresh"]


def test_video_compatibility(tmp_path):
    source = tmp_path / "input.mkv"
    run("ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=30",
        "-f", "lavfi", "-i", "sine=frequency=1000", "-t", "3.2", "-c:v", "libx264", "-c:a", "pcm_s16le",
        str(source))
    result = stage(source, "VIDEO", 0)
    target = MEDIA / result["filename"]
    assert 3 <= result["duration"] < 4
    assert b"aac" in run("ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", str(target))
    target.unlink()


def test_token_expiration():
    expired = account(63, time.time() - 5)
    expired.state = "connected"
    with pytest.raises(MetaError) as exception:
        token(expired)
    assert exception.value.code == 190 and expired.state == "reconnect"


def test_quota_duplicate_and_uncertain_recovery(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://publisher.example")
    media_requests = []
    outcomes = iter([504, 200])

    def mock(request):
        node = request.url.path.rsplit("/", 1)[-1]
        if node == "content_publishing_limit":
            used = next(usage)
            return httpx.Response(200, json={"data": [{"quota_usage": used, "config": {"quota_total": 100}}]})
        if request.method == "POST":
            media_requests.append(node)
        if node == "media":
            return httpx.Response(200, json={"id": "container"})
        if node == "container":
            return httpx.Response(200, json={"status_code": next(container_status)})
        if node == "media_publish":
            return httpx.Response(next(outcomes), json={"error": {"code": 2}})
        return httpx.Response(400, json={"error": {"code": 100}})

    def api(client=None):
        return Instagram(client or httpx.Client(transport=httpx.MockTransport(mock)))

    usage = iter([100, 5])
    container_status = iter(["FINISHED", "PUBLISHED"])
    monkeypatch.setattr("app.worker.Instagram", api)
    filename = "a" * 32 + ".jpg"
    (MEDIA / filename).write_bytes(b"fake bytes for the mocked API")
    with Session.begin() as db:
        db.get(Settings, 1).dry_run = False
        user = account(90)
        original = Media(ig_id="90original", kind="IMAGE", timestamp=1, checksum="matching")
        duplicate = Media(ig_id="90duplicate", kind="IMAGE", timestamp=1, checksum="matching")
        db.add_all([user, original, duplicate])
        db.flush()
        first = Publish(media_id=original.id, account_id=user.id, state="ready", manual=True)
        second = Publish(media_id=duplicate.id, account_id=user.id, state="ready", manual=True)
        db.add_all([first, second, Asset(media_id=original.id, position=0, kind="IMAGE", filename=filename,
                                        mime="image/jpeg", size=27, checksum="matching")])
        db.flush()
        first_id, second_id = first.id, second.id

    publish(first_id)
    with Session.begin() as db:
        first = db.get(Publish, first_id)
        assert first.state == "ready" and first.next_run > time.time()
        first.next_run = 0
    assert not media_requests
    publish(first_id)
    with Session.begin() as db:
        first = db.get(Publish, first_id)
        assert first.state == "uncertain" and first.sent_at
        first.state = "uploading"
    recover()
    publish(first_id)
    publish(second_id)
    with Session.begin() as db:
        assert db.get(Publish, first_id).state == "published"
        assert db.get(Publish, second_id).state == "skipped"
        assert db.scalar(select(Published).where(Published.job_id == first_id))
        assert not eligible(db, db.get(Publish, second_id), db.get(Settings, 1), db.get(Schedule, 1), time.time())
        db.get(Settings, 1).dry_run = True
    assert media_requests == ["media", "media_publish"]
    cleanup()
    assert not (MEDIA / filename).exists()


def test_restart_resets_interrupted_downloads():
    with Session.begin() as db:
        media = Media(ig_id="restart-test", kind="IMAGE", timestamp=1)
        db.add(media)
        db.flush()
        download = Download(media_id=media.id, state="processing")
        db.add(download)
        db.flush()
        identifier = download.id
    recover()
    with Session() as db:
        assert db.get(Download, identifier).state == "pending"


def test_overnight_schedule_and_global_pause():
    zone = ZoneInfo("Asia/Kolkata")
    hours = [datetime(2026, 11, 26, hour, 30, tzinfo=zone).timestamp() for hour in (1, 12, 22)]
    with Session() as db:
        job = Publish(account_id=9001, next_run=0, manual=False)
        settings = Settings(automatic=True, paused=False)
        schedule = Schedule(timezone="Asia/Kolkata", daily=3, interval=120, start="21:00", end="05:00")
        assert next_slot(db, job, settings, schedule, hours[0], None) == hours[0]
        assert next_slot(db, job, settings, schedule, hours[1], None) == hours[2] - 5400
        assert next_slot(db, job, settings, schedule, hours[2], None) == hours[2]
        settings.paused = True
        job.manual = True
        assert next_slot(db, job, settings, schedule, hours[1], None) is None


def test_carousel_containers_survive_processing_delay(monkeypatch):
    payloads = []
    statuses = iter(["IN_PROGRESS", "FINISHED", "FINISHED", "FINISHED", "FINISHED"])

    def mock(request):
        node = request.url.path.rsplit("/", 1)[-1]
        if node == "content_publishing_limit":
            return httpx.Response(200, json={"data": [{"quota_usage": 0, "config": {"quota_total": 50}}]})
        if node in ("media", "media_publish") and request.method == "POST":
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": str(len(payloads))})
        if node == "4":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/result/"})
        return httpx.Response(200, json={"status_code": next(statuses)})

    def api(client=None):
        return Instagram(client or httpx.Client(transport=httpx.MockTransport(mock)))

    monkeypatch.setattr("app.worker.Instagram", api)
    names = ["b" * 32 + ".jpg", "c" * 32 + ".mp4"]
    for name in names:
        (MEDIA / name).write_bytes(b"media fixture")
    with Session.begin() as db:
        db.get(Settings, 1).dry_run = False
        author, media = account(91), Media(ig_id="carousel-91", kind="CAROUSEL_ALBUM", timestamp=1, checksum="carousel")
        db.add_all([author, media])
        db.flush()
        for position, kind in reversed(list(enumerate(["IMAGE", "VIDEO"]))):
            db.add(Asset(media_id=media.id, position=position, kind=kind, filename=names[position], mime="fixture/x",
                         size=13, checksum=f"hash{position}"))
        job = Publish(media_id=media.id, account_id=author.id, state="ready", manual=True)
        db.add(job)
        db.flush()
        identifier = job.id
    publish(identifier)
    with Session.begin() as db:
        job = db.get(Publish, identifier)
        assert job.children == ["1", "2"] and job.state == "ready"
        assert job.next_run > time.time()
        job.next_run = 0
    assert len(payloads) == 2
    publish(identifier)
    assert "/media/" + names[0] in payloads[0]["image_url"]
    assert "/media/" + names[1] in payloads[1]["video_url"]
    assert payloads[2] == {"media_type": "CAROUSEL", "children": "1,2"}
    assert payloads[3] == {"creation_id": "3"}
    with Session.begin() as db:
        assert db.get(Publish, identifier).state == "published"
        assert db.scalar(select(Published).where(Published.job_id == identifier)).permalink.endswith("/result/")
        db.get(Settings, 1).dry_run = True
