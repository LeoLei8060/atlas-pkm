from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI-PKM Agent local server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\nAI-PKM Agent running at {url}\n")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
