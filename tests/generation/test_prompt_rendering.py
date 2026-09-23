import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from prompting import render_prompt


def test_all_prompts_render_for_synthetic():
    sample = {
        "sample_id": "s",
        "repo": "r",
        "data_category": "synthetic_multi",
        "diff_text": "diff --git a/a.py b/a.py\n+print(1)",
        "subject_reference": "add output",
        "intent_count": 2,
        "intent_subjects": ["add output", "update tests"],
        "edit_to_intent": {"h1": 0},
    }
    for strategy in ["G0", "G1", "G2", "G3", "G4", "G5"]:
        prompt = render_prompt(strategy, sample, [])
        assert "Output one line only" in prompt


def test_g5_requires_oracle_structure():
    with pytest.raises(ValueError):
        render_prompt("G5", {"sample_id": "s", "data_category": "hard_b", "diff_text": "x"}, [])

