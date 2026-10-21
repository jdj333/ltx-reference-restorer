"""Acquire only the public institutional editions listed in the fixture catalog.

YouTube retrieval is explicit and never silently switches providers. Acquisition
ledgers contain attribution and hashes, never downloader logs or signed media URLs.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .media import sha256


MAX_BYTES = 2 * 1024 * 1024 * 1024
TIMEOUT_SECONDS = 1800
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,99}\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_ARCHIVE_PATH = re.compile(r"/storage-services/service/mbrs/ntscrm/(\d{8})/\1\.mp4\Z")


def _checked_url(value: str, *, archive: bool = False, video_id: str | None = None) -> str:
    try:
        parsed = urlsplit(value)
        invalid = (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                   or parsed.port is not None or parsed.fragment)
    except (TypeError, ValueError):
        raise ValueError("Public fixture source URL is invalid") from None
    if invalid:
        raise ValueError("Public fixture source URLs require HTTPS without credentials, ports or fragments")
    if archive:
        if parsed.hostname != "tile.loc.gov" or parsed.query or not _ARCHIVE_PATH.fullmatch(parsed.path):
            raise ValueError("Archive sources must be catalogued Library of Congress MP4 viewing copies")
    elif (parsed.hostname != "www.youtube.com" or parsed.path != "/watch"
          or not isinstance(video_id, str) or not _VIDEO.fullmatch(video_id)
          or parse_qsl(parsed.query, keep_blank_values=True) != [("v", video_id)]):
        raise ValueError("YouTube sources must be a single canonical catalogued watch URL")
    return value


def _load_catalog(path: Path) -> tuple[dict, list[dict]]:
    catalog = json.loads(Path(path).read_text())
    films = catalog.get("films")
    if catalog.get("schema_version") != 1 or not isinstance(films, list) or not films:
        raise ValueError("A schema_version 1 public-film catalog is required")
    if catalog.get("rights", {}).get("curated_source_url") != "https://www.loc.gov/free-to-use/public-domain-films-from-the-national-film-registry/":
        raise ValueError("Public fixtures require the catalogued Library of Congress public-domain selection")
    seen = set()
    for film in films:
        identity = film.get("id", "")
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in seen:
            raise ValueError("Catalog film IDs must be unique simple names")
        seen.add(identity)
        youtube, archive = film.get("youtube", {}), film.get("archive", {})
        _checked_url(youtube.get("url"), video_id=youtube.get("video_id"))
        _checked_url(archive.get("download_url"), archive=True)
        if youtube.get("uploader") != "Library of Congress" or youtube.get("uploader_url") != "https://www.youtube.com/@loc":
            raise ValueError("Public fixtures require the Library of Congress YouTube uploader")
        expected = archive.get("expected_size_bytes")
        if isinstance(expected, bool) or not isinstance(expected, int) or not 1 <= expected <= MAX_BYTES:
            raise ValueError("Archive catalog requires a bounded expected byte size")
        if archive.get("download_restricted") is not False or archive.get("can_download") is not True:
            raise ValueError("Archive source is not explicitly available for download")
        if archive.get("sha256") and not _HASH.fullmatch(archive["sha256"]):
            raise ValueError("Archive SHA-256 must be a lowercase 64-character digest")
    return catalog, films


class _ArchiveRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _checked_url(newurl, archive=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_archive(film: dict, destination: Path) -> dict:
    archive = film["archive"]
    expected = archive["expected_size_bytes"]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    request = Request(archive["download_url"], headers={"User-Agent": "LTX-Reference-Restorer-public-fixtures/" + __version__})
    try:
        with build_opener(_ArchiveRedirects()).open(request, timeout=30) as response, destination.open("xb") as output:
            _checked_url(response.geturl(), archive=True)
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != expected:
                raise ValueError("Archive response size differs from the reviewed catalog")
            total = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected or total > MAX_BYTES:
                    raise ValueError("Archive response exceeds its reviewed size")
                output.write(chunk)
            if total != expected:
                raise ValueError("Archive download is incomplete")
    except ValueError:
        raise
    except Exception:
        raise RuntimeError("Archive acquisition failed; no complete ledger was written") from None
    return {}


def _download_youtube(film: dict, destination: Path) -> dict:
    # Ignore user/system yt-dlp configuration so cookies and external downloaders
    # cannot be enabled incidentally. Only this public watch URL is passed through.
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-cache-dir",
        "--no-progress", "--quiet", "--no-warnings", "--no-colors", "--no-overwrites", "--no-mtime",
        "--socket-timeout", "30", "--retries", "2", "--fragment-retries", "2",
        "--max-filesize", str(MAX_BYTES), "--merge-output-format", "mp4", "--remux-video", "mp4",
        "--format", "bestvideo[height<=720][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][vcodec^=avc1][ext=mp4]",
        "--output", str(destination), "--print", "after_move:%(.{id,title,uploader,channel,duration,ext})j",
    ]
    if node := shutil.which("node"):
        command += ["--js-runtimes", "node:" + node]
    command.append(film["youtube"]["url"])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True)
        metadata = json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception:
        # Downloader diagnostics can contain signed media URLs or local paths.
        raise RuntimeError("YouTube acquisition failed; no complete ledger was written. The explicit archive provider is available separately.") from None
    youtube = film["youtube"]
    if (not isinstance(metadata, dict) or metadata.get("id") != youtube["video_id"]
            or (metadata.get("uploader") != youtube["uploader"] and metadata.get("channel") != youtube["uploader"])
            or metadata.get("ext") != "mp4"):
        raise ValueError("Downloaded YouTube metadata does not match the catalogued institutional upload")
    return metadata


def _identity(film: dict, source: str) -> tuple[str, str]:
    if source == "youtube":
        return film["youtube"]["url"], "YouTube upload " + film["youtube"]["video_id"]
    return film["archive"]["download_url"], film["archive"]["edition"]


def _existing(directory: Path, film: dict, source: str) -> dict | None:
    media, ledger_path = directory / "source.mp4", directory / "acquisition.json"
    if media.is_symlink() or ledger_path.is_symlink():
        raise ValueError("Acquisition media and ledgers must not be symbolic links")
    if not media.exists() and not ledger_path.exists():
        return None
    try:
        ledger = json.loads(ledger_path.read_text())
        source_url, edition = _identity(film, source)
        if (not media.is_file() or ledger.get("schema_version") != 1 or ledger.get("status") != "complete"
                or ledger.get("film_id") != film["id"] or ledger.get("provider") != source
                or ledger.get("source_url") != source_url or ledger.get("edition") != edition
                or ledger.get("file") != "source.mp4" or ledger.get("size_bytes") != media.stat().st_size
                or not 1 <= media.stat().st_size <= MAX_BYTES
                or not isinstance(ledger.get("sha256"), str) or not _HASH.fullmatch(ledger["sha256"])
                or sha256(media) != ledger["sha256"]):
            raise ValueError
        if source == "archive" and (media.stat().st_size != film["archive"]["expected_size_bytes"]
                                    or (film["archive"].get("sha256") and ledger["sha256"] != film["archive"]["sha256"])):
            raise ValueError
        return ledger
    except (OSError, ValueError, TypeError):
        raise ValueError("Existing acquisition is incomplete, mismatched or has changed; preserve it and use a new output directory") from None


def fetch_films(catalog_path: Path, output_dir: Path, *, film_ids: list[str] | None = None, source: str = "youtube") -> dict:
    """Fetch selected catalog films and return the complete acquisition ledgers.

    Valid existing media are hash-verified and reused. Other existing files are
    preserved and rejected. A failed download never creates a complete ledger.
    """
    if source not in ("youtube", "archive"):
        raise ValueError("Source must be youtube or archive")
    catalog, films = _load_catalog(catalog_path)
    if film_ids is not None:
        requested = set(film_ids)
        if not requested or requested - {film["id"] for film in films}:
            raise ValueError("Select at least one known catalog film ID")
        films = [film for film in films if film["id"] in requested]
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for film in films:
        directory = root / film["id"]
        if directory.is_symlink() or directory.resolve() != directory:
            raise ValueError("Film output directory must stay inside the acquisition directory")
        directory.mkdir(exist_ok=True)
        existing = _existing(directory, film, source)
        if existing:
            results.append(existing)
            continue
        with tempfile.TemporaryDirectory(prefix=".acquire-", dir=directory) as staging:
            staged = Path(staging) / "source.mp4"
            metadata = _download_youtube(film, staged) if source == "youtube" else _download_archive(film, staged)
            if not staged.is_file() or staged.is_symlink() or not 1 <= staged.stat().st_size <= MAX_BYTES:
                raise ValueError("Downloaded public film is missing or exceeds the size limit")
            digest = sha256(staged)
            archive = film["archive"]
            if source == "archive" and (staged.stat().st_size != archive["expected_size_bytes"]
                                       or (archive.get("sha256") and digest != archive["sha256"])):
                raise ValueError("Archive download does not match the reviewed catalog")
            source_url, edition = _identity(film, source)
            try:
                downloader_version = importlib.metadata.version("yt-dlp") if source == "youtube" else None
            except importlib.metadata.PackageNotFoundError:
                downloader_version = None
            ledger = {
                "schema_version": 1, "status": "complete", "film_id": film["id"], "provider": source,
                "source_url": source_url, "edition": edition,
                "acquired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "file": "source.mp4", "sha256": digest, "size_bytes": staged.stat().st_size,
                "rights_url": catalog["rights"]["curated_source_url"],
                "versions": {"restorer": __version__, "python": platform.python_version(), "yt_dlp": downloader_version},
            }
            if source == "youtube":
                ledger["youtube"] = {key: film["youtube"][key] for key in ("video_id", "title", "uploader", "uploader_url")}
                if isinstance(metadata.get("duration"), (int, float)):
                    ledger["youtube"]["duration_seconds"] = metadata["duration"]
            staged_ledger = Path(staging) / "acquisition.json"
            staged_ledger.write_text(json.dumps(ledger, indent=2) + "\n")
            # Hard links fail if another process created the destination, preventing
            # an accidental overwrite between the existence check and publication.
            (directory / "source.mp4").hardlink_to(staged)
            (directory / "acquisition.json").hardlink_to(staged_ledger)
            results.append(ledger)
    return {"schema_version": 1, "films": results}
