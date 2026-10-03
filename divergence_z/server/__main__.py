"""サイドカー起動。

    python -m divergence_z.server [--port 0] [--allow-origin app://-]

起動すると stdout に1行だけ JSON を出す（Electron はこれを読んで接続先を知る）:
    {"event": "ready", "host": "127.0.0.1", "port": 53817, "token": "..."}
以降のログは stderr。親プロセスが消えたら自動で終了する。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time

import uvicorn

from .app import create_app


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _watch_parent(parent_pid: int) -> None:
    """親（Electron）が終了したら道連れで終了する"""
    while True:
        time.sleep(2)
        if os.getppid() != parent_pid:
            os._exit(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Divergence-Z sidecar API")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (loopback only; default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    parser.add_argument("--token", default=os.getenv("DZ_TOKEN") or "",
                        help="Auth token (default: random per launch)")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="CORS origin allowed to call the API (repeatable), e.g. app://- or "
                             "http://localhost:5173 for the dev server")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent jobs")
    parser.add_argument("--no-parent-watch", action="store_true")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("the sidecar only binds to loopback")
    token = args.token or secrets.token_urlsafe(32)
    port = args.port or _free_port(args.host)

    if not args.no_parent_watch:
        threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()

    app = create_app(token, allowed_origins=args.allow_origin, max_workers=args.workers)
    print(json.dumps({"event": "ready", "host": args.host, "port": port, "token": token}),
          flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
