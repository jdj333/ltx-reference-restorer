import shutil

import pytest

from restorer.config import Settings
from restorer.media import run


@pytest.fixture
def settings(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real FFmpeg and ffprobe required")
    return Settings(data_dir=tmp_path / "data", import_roots=(tmp_path,))


@pytest.fixture
def movie(tmp_path, settings):
    path = tmp_path / "input.mp4"
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2", str(path)])
    return path
