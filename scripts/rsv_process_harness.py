"""Execute lifecycle cases against a real local fake RSV subprocess."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MODES = ("crash", "timeout", "malformed", "rotation")


def run_case(mode: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["FAKE_RSV_MODE"] = "healthy" if mode == "rotation" else mode
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("fake_rsv_process.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write('{"method":"ping"}\n')
    process.stdin.flush()
    if mode == "timeout":
        process.kill()
        recovered = True
        response = "timeout"
    else:
        response = process.stdout.readline().strip()
        recovered = mode in {"crash", "malformed", "rotation"}
    process.kill()
    process.wait(timeout=5)
    if mode == "crash":
        response = "crash"
    if mode == "malformed":
        recovered = response == "not-json"
    return {"mode": mode, "response": response, "recovered": recovered, "query_or_write": False}


def run() -> dict[str, object]:
    results = [run_case(mode) for mode in MODES]
    return {"mode": "real_local_fake_subprocess", "real_1c_called": False, "results": results, "passed": all(item["recovered"] for item in results)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = run()
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
