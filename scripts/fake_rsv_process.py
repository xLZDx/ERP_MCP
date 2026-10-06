"""Tiny JSON-lines fake RSV process used by the lifecycle harness only."""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    mode = os.environ.get("FAKE_RSV_MODE", "healthy")
    for line in sys.stdin:
        request = json.loads(line)
        if mode == "crash":
            raise SystemExit(17)
        if mode == "timeout":
            import time

            time.sleep(30)
        if mode == "malformed":
            sys.stdout.write("not-json\n")
        else:
            sys.stdout.write(json.dumps({"ok": True, "method": request.get("method")}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
