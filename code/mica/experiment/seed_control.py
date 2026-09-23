from __future__ import annotations

import os
import random
from typing import Any


def set_reproducible_seed(seed: int) -> dict[str, Any]:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np  # type: ignore

        np.random.seed(seed)
        numpy_enabled = True
    except Exception:
        numpy_enabled = False
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():  # pragma: no cover - environment dependent
            torch.cuda.manual_seed_all(seed)
        torch_enabled = True
    except Exception:
        torch_enabled = False
    return {
        "seed": int(seed),
        "python_hash_seed": os.environ["PYTHONHASHSEED"],
        "numpy_enabled": numpy_enabled,
        "torch_enabled": torch_enabled,
    }
