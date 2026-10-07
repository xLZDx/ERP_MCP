"""``python -m onec_com_bridge --config <file>`` (Windows host, loopback only)."""
from __future__ import annotations

import argparse
import logging

import uvicorn

from .app import create_app
from .config import load_config, read_token
from .runtime import Win32ComRuntime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onec_com_bridge")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    app = create_app(config, token=read_token(config.token_file), runtime=Win32ComRuntime())
    uvicorn.run(app, host=config.listen_host, port=config.listen_port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
