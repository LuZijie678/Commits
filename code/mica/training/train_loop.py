from __future__ import annotations

from typing import Any


def summarize_train_loop_capabilities(*, implementation_only: bool) -> dict[str, Any]:
    return {
        "implementation_only": implementation_only,
        "trainer_backend_executable": True,
        "trainer_backend_executed": False,
        "checkpoint_writes_enabled": False,
        "runtime_output_writes_enabled": False,
        "supported_backends": ["toy_attribution_backend"],
        "supported_stages": ["stage2", "stage3"],
    }
