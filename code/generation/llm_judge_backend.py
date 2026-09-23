from __future__ import annotations

from typing import Any

from llm_backend import LLMBackend


class LLMJudgeBackend(LLMBackend):
    """Separate judge backend wrapper. Defaults remain mock/disabled in configs."""

    def judge(self, prompt: str) -> dict[str, Any]:
        result = self.generate(prompt)
        if result.get("status") == "generated" and self.provider == "mock":
            result["judge_scores"] = {
                "correctness": "not_applicable_mock",
                "completeness": "not_applicable_mock",
                "faithfulness": "not_applicable_mock",
                "conciseness": "not_applicable_mock",
                "readability": "not_applicable_mock",
                "overall_score": "not_applicable_mock",
            }
        return result

