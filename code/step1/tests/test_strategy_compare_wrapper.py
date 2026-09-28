from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_step1_strategy_compare.py"
SPEC = importlib.util.spec_from_file_location("run_step1_strategy_compare", SCRIPT)
WRAPPER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(WRAPPER)


def test_default_command_uses_active_python_and_historical_settings() -> None:
    command = WRAPPER.build_command({})
    assert command[:3] == [sys.executable, "-m", "src.pipeline.run_step1"]
    assert command[command.index("--allcommits") + 1].startswith("../../datasets/step1/")
    assert "--fetch-diff" in command
    assert "--strict-gates" in command
    assert "--no-require-audit-completion" in command
    assert "--run-proxy-gap-analysis" in command


def test_env_overrides_are_passed_as_arguments_not_shell_text() -> None:
    command = WRAPPER.build_command(
        {
            "RUN_NAME": "run with spaces",
            "FETCH_DIFF": "false",
            "STRICT_GATES": "false",
            "AUDIT_LABELED_CSV": "C:\\research data\\audit.csv",
        }
    )
    assert command[command.index("--run-name") + 1] == "run with spaces"
    assert "--fetch-diff" not in command
    assert "--no-strict-gates" in command
    assert command[-2:] == ["--audit-labeled-csv", "C:\\research data\\audit.csv"]


def test_main_runs_from_step1_directory(monkeypatch) -> None:
    calls = []

    def fake_run(command, *, cwd, check):
        calls.append((command, cwd, check))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(WRAPPER.subprocess, "run", fake_run)
    assert WRAPPER.main() == 7
    assert calls[0][1] == WRAPPER.STEP1_DIR
    assert calls[0][2] is False
