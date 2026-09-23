#!/usr/bin/env python3
"""Emit shell exports for HTTP/HTTPS proxy from macOS system proxy settings."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print shell export lines for proxy environment variables from macOS system proxy settings."
    )
    parser.add_argument(
        "--format",
        choices=["shell"],
        default="shell",
        help="Output format. Currently only shell export lines are supported.",
    )
    return parser.parse_args()


def parse_scutil_proxy(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    pattern = re.compile(r"^\s*([A-Za-z0-9]+)\s*:\s*(.+?)\s*$")
    for line in stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        values[match.group(1)] = match.group(2)
    return values


def build_proxy_exports(values: dict[str, str]) -> list[str]:
    exports: list[str] = []
    http_enable = values.get("HTTPEnable") == "1"
    https_enable = values.get("HTTPSEnable") == "1"

    if http_enable:
        host = values.get("HTTPProxy", "")
        port = values.get("HTTPPort", "")
        if host and port:
            exports.append(f'export HTTP_PROXY="http://{host}:{port}"')
            exports.append(f'export http_proxy="http://{host}:{port}"')

    if https_enable:
        host = values.get("HTTPSProxy", "")
        port = values.get("HTTPSPort", "")
        if host and port:
            exports.append(f'export HTTPS_PROXY="http://{host}:{port}"')
            exports.append(f'export https_proxy="http://{host}:{port}"')

    return exports


def main() -> int:
    _ = parse_args()
    try:
        result = subprocess.run(
            ["scutil", "--proxy"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return 0
    if result.returncode != 0:
        return 0

    values = parse_scutil_proxy(result.stdout or "")
    exports = build_proxy_exports(values)
    if not exports:
        return 0
    sys.stdout.write("\n".join(exports) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
