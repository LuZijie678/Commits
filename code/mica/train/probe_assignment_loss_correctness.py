from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.losses.mica_losses import compute_stage1_losses
from code.mica.models.mica_model import MicaOutput


def _output(assignment_probs: torch.Tensor) -> MicaOutput:
    return MicaOutput(
        slot_logits=torch.tensor([[3.0, 3.0, -4.0, -4.0]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.95, 0.95, 0.01, 0.01]], dtype=torch.float32),
        assignment_logits=torch.zeros(1, 4, assignment_probs.size(-1), dtype=torch.float32),
        assignment_probs=assignment_probs.unsqueeze(0),
        count_logits=torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32),
        count_probs=torch.softmax(torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32), dim=-1),
        pb_count_probs=torch.tensor([[0.10, 0.80, 0.05, 0.05]], dtype=torch.float32),
    )


def run_assignment_loss_correctness_probe() -> dict[str, Any]:
    targets = {
        "gold_counts": torch.tensor([2], dtype=torch.long),
        "gold_assignment_masks": [
            torch.tensor(
                [[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]],
                dtype=torch.float32,
            )
        ],
        "unit_mask": torch.tensor([[True, True, True, True]]),
    }
    perfect = _output(
        torch.tensor(
            [
                [0.95, 0.90, 0.05, 0.10],
                [0.05, 0.10, 0.95, 0.90],
                [0.00, 0.00, 0.00, 0.00],
                [0.00, 0.00, 0.00, 0.00],
            ],
            dtype=torch.float32,
        )
    )
    swapped = _output(
        torch.tensor(
            [
                [0.05, 0.10, 0.95, 0.90],
                [0.95, 0.90, 0.05, 0.10],
                [0.00, 0.00, 0.00, 0.00],
                [0.00, 0.00, 0.00, 0.00],
            ],
            dtype=torch.float32,
        )
    )
    all_one = _output(
        torch.tensor(
            [
                [0.99, 0.98, 0.97, 0.96],
                [0.01, 0.02, 0.03, 0.04],
                [0.00, 0.00, 0.00, 0.00],
                [0.00, 0.00, 0.00, 0.00],
            ],
            dtype=torch.float32,
        )
    )
    perfect_losses = compute_stage1_losses(perfect, targets, lambda_count=0.0, lambda_exist=0.0, lambda_stab=0.0)
    swapped_losses = compute_stage1_losses(swapped, targets, lambda_count=0.0, lambda_exist=0.0, lambda_stab=0.0)
    all_one_losses = compute_stage1_losses(all_one, targets, lambda_count=0.0, lambda_exist=0.0, lambda_stab=0.0)
    perfect_align = float(perfect_losses["loss_align"].item())
    swapped_align = float(swapped_losses["loss_align"].item())
    all_one_align = float(all_one_losses["loss_align"].item())
    return {
        "perfect_align_loss": perfect_align,
        "swapped_align_loss": swapped_align,
        "all_one_align_loss": all_one_align,
        "perfect_beats_all_one": perfect_align + 0.10 < all_one_align,
        "swapped_equivalent_to_perfect": abs(perfect_align - swapped_align) < 1e-5,
        "align_loss_margin_perfect_vs_all_one": all_one_align - perfect_align,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Probe MICA Stage 1 assignment loss correctness.")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    parser.parse_args(argv)
    result = run_assignment_loss_correctness_probe()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
