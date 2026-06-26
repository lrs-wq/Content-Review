from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8050, type=int)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    handler = functools.partial(Handler, directory=str(root))

    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"Content review UI: http://{args.host}:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
