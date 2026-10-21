from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

from .config import load_settings


def main():
    parser = argparse.ArgumentParser(description="Local source-led film restoration")
    parser.add_argument("command", choices=["start", "serve", "worker", "doctor", "demo"])
    args = parser.parse_args()
    settings = load_settings()
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
