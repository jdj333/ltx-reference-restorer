"""Acquisition boundaries and durable provenance, without network downloads."""
import io
import json
import subprocess
from pathlib import Path

import pytest

from restorer import public_acquire as acquisition


@pytest.fixture
def catalog(tmp_path):
    data = json.loads((Path(__file__).parents[1] / "fixtures/public-films/catalog.json").read_text())
    data["films"] = data["films"][:1]
    data["films"][0]["archive"]["expected_size_bytes"] = 4
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data))
    return path


def write_media(film, destination):
    destination.write_bytes(b"film")
    return {"duration": 2.04}


def test_youtube_acquisition_has_exact_provider_hash_and_reuses_verified_media(catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "_download_youtube", write_media)
    output = tmp_path / "downloads"
    result = acquisition.fetch_films(catalog, output)
    ledger = result["films"][0]
    assert ledger["status"] == "complete"
    assert ledger["provider"] == "youtube"
    assert ledger["edition"] == "YouTube upload hdoRQ2iqh8I"
    assert ledger["source_url"] == "https://www.youtube.com/watch?v=hdoRQ2iqh8I"
    assert ledger["youtube"]["duration_seconds"] == 2.04
    assert ledger["sha256"] == acquisition.sha256(output / ledger["film_id"] / "source.mp4")
    text = (output / ledger["film_id"] / "acquisition.json").read_text()
    assert str(tmp_path) not in text
    assert "signed" not in text
    monkeypatch.setattr(acquisition, "_download_youtube", lambda *args: pytest.fail("Valid acquisition must be reused"))
    assert acquisition.fetch_films(catalog, output) == result
    (output / ledger["film_id"] / "source.mp4").write_bytes(b"edit")
    with pytest.raises(ValueError, match="has changed"):
        acquisition.fetch_films(catalog, output)
    assert (output / ledger["film_id"] / "source.mp4").read_bytes() == b"edit"


def test_archive_is_an_explicit_distinct_edition(catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "_download_archive", write_media)
    ledger = acquisition.fetch_films(catalog, tmp_path / "downloads", source="archive")["films"][0]
    assert ledger["provider"] == "archive"
    assert ledger["source_url"].startswith("https://tile.loc.gov/")
    assert "YouTube" not in ledger["edition"]
    assert "youtube" not in ledger
    with pytest.raises(ValueError, match="mismatched"):
        acquisition.fetch_films(catalog, tmp_path / "downloads", source="youtube")


def test_youtube_failure_never_falls_back_or_marks_complete(catalog, tmp_path, monkeypatch):
    def fail(film, destination):
        destination.write_bytes(b"part")
        raise RuntimeError("Blocked")
    monkeypatch.setattr(acquisition, "_download_youtube", fail)
    monkeypatch.setattr(acquisition, "_download_archive", lambda *args: pytest.fail("No automatic provider fallback"))
    output = tmp_path / "downloads"
    with pytest.raises(RuntimeError, match="Blocked"):
        acquisition.fetch_films(catalog, output)
    assert not list(output.rglob("source.mp4"))
    assert not list(output.rglob("acquisition.json"))
    assert not list(output.rglob(".acquire-*"))


@pytest.mark.parametrize("mutation", [
    lambda data: data["films"][0].update(id="../../escape"),
    lambda data: data["films"][0]["youtube"].update(url="https://user:secret@www.youtube.com/watch?v=hdoRQ2iqh8I"),
    lambda data: data["films"][0]["youtube"].update(url="http://www.youtube.com/watch?v=hdoRQ2iqh8I"),
    lambda data: data["films"][0]["youtube"].update(url="https://www.youtube.com/watch?v=hdoRQ2iqh8I&list=private"),
    lambda data: data["films"][0]["archive"].update(download_url="https://example.com/film.mp4"),
    lambda data: data["films"][0]["archive"].update(download_url="https://tile.loc.gov/private/film.mp4?signature=secret"),
    lambda data: data["films"][0]["archive"].update(download_restricted=True),
    lambda data: data["films"][0]["archive"].update(expected_size_bytes=acquisition.MAX_BYTES + 1),
])
def test_rejects_unreviewed_sources_before_download(catalog, tmp_path, mutation, monkeypatch):
    data = json.loads(catalog.read_text())
    mutation(data)
    catalog.write_text(json.dumps(data))
    monkeypatch.setattr(acquisition, "_download_youtube", lambda *args: pytest.fail("Invalid source must not be downloaded"))
    with pytest.raises(ValueError):
        acquisition.fetch_films(catalog, tmp_path / "downloads")


def test_unknown_selection_rejected(catalog, tmp_path):
    with pytest.raises(ValueError, match="known"):
        acquisition.fetch_films(catalog, tmp_path / "downloads", film_ids=["missing"])


def test_symlink_and_existing_partial_are_preserved(catalog, tmp_path, monkeypatch):
    output = tmp_path / "downloads"
    output.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    directory = output / "st-louis-blues-1929"
    directory.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="stay inside"):
        acquisition.fetch_films(catalog, output)
    directory.unlink()
    directory.mkdir()
    (directory / "source.mp4").write_bytes(b"part")
    monkeypatch.setattr(acquisition, "_download_youtube", lambda *args: pytest.fail("Must preserve partial media"))
    with pytest.raises(ValueError, match="incomplete"):
        acquisition.fetch_films(catalog, output)
    assert (directory / "source.mp4").read_bytes() == b"part"


def test_archive_size_and_optional_hash_must_match(catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "_download_archive", write_media)
    data = json.loads(catalog.read_text())
    data["films"][0]["archive"]["sha256"] = "0" * 64
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reviewed catalog"):
        acquisition.fetch_films(catalog, tmp_path / "downloads", source="archive")
    assert not list((tmp_path / "downloads").rglob("acquisition.json"))


def test_youtube_command_ignores_config_and_exports_only_narrow_metadata(catalog, tmp_path, monkeypatch):
    film = json.loads(catalog.read_text())["films"][0]
    destination = tmp_path / "source.mp4"
    seen = []
    def run(command, **kwargs):
        seen.extend(command)
        assert kwargs["timeout"] == acquisition.TIMEOUT_SECONDS
        assert kwargs["check"]
        destination.write_bytes(b"film")
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "id": film["youtube"]["video_id"], "uploader": "Library of Congress", "duration": 2, "ext": "mp4",
        }), "")
    monkeypatch.setattr(acquisition.subprocess, "run", run)
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: "/usr/local/bin/node")
    acquisition._download_youtube(film, destination)
    assert "--ignore-config" in seen
    assert "--no-playlist" in seen
    assert "--js-runtimes" in seen
    assert "node:/usr/local/bin/node" in seen
    assert "--cookies" not in seen
    assert "--cookies-from-browser" not in seen
    assert "--write-info-json" not in seen
    assert "height<=720" in seen[seen.index("--format") + 1]


def test_youtube_diagnostics_never_escape_into_error(catalog, tmp_path, monkeypatch):
    film = json.loads(catalog.read_text())["films"][0]
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["yt-dlp"], stderr="https://media.example/file?signature=secret")
    monkeypatch.setattr(acquisition.subprocess, "run", fail)
    with pytest.raises(RuntimeError) as error:
        acquisition._download_youtube(film, tmp_path / "source.mp4")
    assert "signature" not in str(error.value)
    assert "secret" not in str(error.value)


def test_real_youtube_formatter_exports_metadata_object(catalog, tmp_path, monkeypatch):
    youtube = pytest.importorskip("yt_dlp")
    film = json.loads(catalog.read_text())["films"][0]
    expected = {
        "id": film["youtube"]["video_id"], "title": "St. Louis Blues",
        "uploader": "Library of Congress", "channel": "Library of Congress", "duration": 956, "ext": "mp4",
    }
    def run(command, **kwargs):
        template = command[command.index("--print") + 1].split(":", 1)[1]
        # Exercise yt-dlp's actual formatter; a syntactically plausible template
        # can otherwise serialize just a scalar ID instead of the intended object.
        rendered = youtube.YoutubeDL({"quiet": True}).evaluate_outtmpl(template, {
            **expected, "url": "https://media.example/file?signature=secret",
        })
        assert json.loads(rendered) == expected
        assert "signature" not in rendered
        return subprocess.CompletedProcess(command, 0, rendered, "")
    monkeypatch.setattr(acquisition.subprocess, "run", run)
    assert acquisition._download_youtube(film, tmp_path / "source.mp4") == expected


@pytest.mark.parametrize("metadata", ["hdoRQ2iqh8I", None, [], 42])
def test_youtube_rejects_scalar_or_nonobject_metadata(catalog, tmp_path, monkeypatch, metadata):
    film = json.loads(catalog.read_text())["films"][0]
    monkeypatch.setattr(acquisition.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, json.dumps(metadata), "",
    ))
    with pytest.raises(ValueError, match="institutional upload"):
        acquisition._download_youtube(film, tmp_path / "source.mp4")


def test_archive_stream_size_is_enforced_and_redirects_are_restricted(catalog, tmp_path, monkeypatch):
    film = json.loads(catalog.read_text())["films"][0]
    class Response(io.BytesIO):
        headers = {"Content-Length": "4"}
        def geturl(self):
            return film["archive"]["download_url"]
    class Opener:
        def open(self, request, timeout):
            return Response(b"film")
    monkeypatch.setattr(acquisition, "build_opener", lambda *args: Opener())
    destination = tmp_path / "source.mp4"
    acquisition._download_archive(film, destination)
    assert destination.read_bytes() == b"film"
    with pytest.raises(ValueError, match="Library of Congress"):
        acquisition._ArchiveRedirects().redirect_request(None, None, 302, "Found", {}, "https://example.com/film.mp4")


def test_archive_truncation_never_publishes_a_ledger(catalog, tmp_path, monkeypatch):
    film = json.loads(catalog.read_text())["films"][0]
    class Response(io.BytesIO):
        headers = {}
        def geturl(self):
            return film["archive"]["download_url"]
    class Opener:
        def open(self, request, timeout):
            return Response(b"bad")
    monkeypatch.setattr(acquisition, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError, match="incomplete"):
        acquisition.fetch_films(catalog, tmp_path / "downloads", source="archive")
    assert not list((tmp_path / "downloads").rglob("acquisition.json"))
