"""Isolated real API/worker for browser regression tests; synthetic media only."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import uvicorn
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from restorer.api import create_app
from restorer.config import Settings
from restorer.media import run


def main():
    port = int(os.environ.get("RESTORER_E2E_PORT", "8879"))
    with tempfile.TemporaryDirectory(prefix="ltx-browser-e2e-") as temporary:
        folder = Path(temporary)
        media = folder / "media"
        media.mkdir()
        image = Image.new("RGB", (320, 180), (32, 42, 56))
        draw = ImageDraw.Draw(image)
        draw.ellipse((120, 20, 200, 130), fill=(218, 170, 116))
        draw.text((12, 150), "SYNTHETIC BROWSER TEST", fill="white")
        image.save(media / "synthetic-reference.png")
        run(["ffmpeg", "-nostdin", "-v", "error", "-loop", "1", "-i", str(media / "synthetic-reference.png"),
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-r", "12",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3",
             "-movflags", "+faststart", str(media / "synthetic-source.mp4")])
        settings = Settings(data_dir=folder / "app", port=port, import_roots=(media,), comfy_url="http://127.0.0.1:1")
        config = folder / "config.toml"
        config.write_text("[restorer]\n" + "\n".join([
            f"data_dir = {json.dumps(str(settings.data_dir))}", f"port = {port}",
            f"import_roots = [{json.dumps(str(media))}]", 'comfy_url = "http://127.0.0.1:1"',
        ]) + "\n")
        # Never inherit a user's ordinary data directory or model endpoint.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("RESTORER_")}
        environment.update(RESTORER_CONFIG=str(config), PYTHONPATH=str(ROOT / "backend"))
        worker = subprocess.Popen([sys.executable, "-m", "restorer.cli", "worker"], env=environment, start_new_session=True)
        # Uvicorn re-raises its captured termination signal after shutdown.
        # Preserve Python's finally path so the separately owned worker is
        # stopped before the temporary application directory is removed.
        def stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            uvicorn.run(create_app(settings), host="127.0.0.1", port=port, access_log=False)
        except KeyboardInterrupt:
            pass
        finally:
            if worker.poll() is None:
                worker.send_signal(signal.SIGINT)
                try:
                    worker.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()


if __name__ == "__main__":
    main()
