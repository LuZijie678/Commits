from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"


@pytest.mark.parametrize("filename", ["construct_simple_two_intent.py", "run_step2_fullscale_sharded.py"])
def test_broken_pipe_uses_platform_null_device(monkeypatch, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), CODE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    opened = []
    sink = io.StringIO()
    original_stdout = sys.stdout

    def broken_print(*args, **kwargs):
        raise BrokenPipeError

    def fake_open(path, mode, *, encoding):
        opened.append((path, mode, encoding))
        return sink

    monkeypatch.setattr(module, "print", broken_print, raising=False)
    monkeypatch.setattr(module, "open", fake_open, raising=False)
    try:
        module.safe_print("closed consumer")
    finally:
        sys.stdout = original_stdout
    assert opened == [(os.devnull, "w", "utf-8")]
