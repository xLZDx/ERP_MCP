"""Run the test IdP: ``python -m testbed.idp`` (loopback only, no access log)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import uvicorn

from .app import create_app

if __name__ == "__main__":
    config_path = os.environ.get("E2E_IDP_CONFIG")
    if not config_path:
        raise SystemExit("E2E_IDP_CONFIG must point to the generated .e2e/idp-config.json")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if config["host"] != "127.0.0.1":
        raise SystemExit("the test IdP binds to 127.0.0.1 only")
    uvicorn.run(create_app(config), host=config["host"], port=int(config["port"]),
                access_log=False, log_level="info")
