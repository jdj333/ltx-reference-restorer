from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from dataclasses import replace

from .config import load_settings


def main():
    parser = argparse.ArgumentParser(description="Local source-led film restoration")
    parser.add_argument("command", choices=["start", "serve", "worker", "doctor", "demo", "public-fetch", "public-prepare", "public-demo"])
    fixture_root = Path(__file__).resolve().parents[2] / "fixtures" / "public-films"
    parser.add_argument("--catalog", type=Path, default=fixture_root / "catalog.json")
    parser.add_argument("--selections", type=Path, default=fixture_root / "selections.json")
    parser.add_argument("--media-dir", type=Path, default=Path(".data/public-films/media"))
    parser.add_argument("--output-dir", type=Path, default=Path(".data/public-films/prepared"))
    parser.add_argument("--manifest", type=Path, default=Path(".data/public-films/prepared/manifest.json"))
    parser.add_argument("--source", choices=["youtube", "archive"], default="youtube")
    parser.add_argument("--film", action="append", help="Catalog film ID; repeat to select more films")
    parser.add_argument("--backend", choices=["baseline", "comfy_restore", "comfy_refine"], default="baseline")
    parser.add_argument("--scale", type=int, choices=[1, 2, 3, 4], default=2)
    parser.add_argument("--data-dir", type=Path, help="Fresh public-demo app directory (default .data/public-films/app)")
    parser.add_argument("--report", type=Path, help="Public-demo safe JSON report destination")
    args = parser.parse_args()
    if args.command == "public-fetch":
        from .public_acquire import fetch_films
        print(json.dumps(fetch_films(args.catalog, args.media_dir, film_ids=args.film, source=args.source), indent=2))
        return
    settings = load_settings()
    if args.command == "public-prepare":
        from .public_prepare import prepare_fixtures
        manifest = prepare_fixtures(args.catalog, args.selections, args.media_dir, args.output_dir, settings)
        print(json.dumps({"manifest": str(args.output_dir / "manifest.json"), "fixtures": [f["id"] for f in manifest["fixtures"]]}, indent=2))
        return
    if args.command == "public-demo":
        from .public_demo import run_public_demo
        # Public test commands never fall through to the ordinary project directory.
        settings = replace(settings, data_dir=args.data_dir or Path(".data/public-films/app"))
        report = run_public_demo(settings, args.manifest, backend=args.backend, scale=args.scale, report_path=args.report)
        print(json.dumps(report, indent=2))
        if report["status"] != "passed":
            raise SystemExit(2 if report["status"] == "blocked" else 1)
        return
    settings.initialize()
    if args.command == "doctor":
        from .doctor import report
        print(json.dumps(report(settings), indent=2))
    elif args.command == "demo":
        from .demo import create_demo
        print(json.dumps(create_demo(settings), indent=2))
    elif args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    elif args.command == "worker":
        from .worker import Worker
        def stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            Worker(settings).loop()
        except KeyboardInterrupt:
            pass
    else:
        def stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        children = []
        try:
            for command in ("worker", "serve"):
                # The terminal signals the supervisor once; it then gracefully
                # signals each owned child, avoiding duplicate Ctrl-C delivery.
                children.append(subprocess.Popen([sys.executable, "-m", "restorer.cli", command], start_new_session=True))
            print(f"Restorer: http://{settings.host}:{settings.port} (Ctrl+C stops API and worker)", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(0.4)
            if any(child.returncode not in (None, 0) for child in children):
                raise RuntimeError("A child process exited; see its error above")
        except KeyboardInterrupt:
            pass
        finally:
            for child in children:
                if child.poll() is None:
                    child.send_signal(signal.SIGINT)
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
