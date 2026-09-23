from __future__ import annotations

import copy
from typing import Any

import torch


class EMATeacher:
    def __init__(self, model_or_backend: Any, decay: float = 0.999) -> None:
        self.decay = float(decay)
        self.teacher_backend = copy.deepcopy(model_or_backend)
        if hasattr(self.teacher_backend, "set_eval_mode"):
            self.teacher_backend.set_eval_mode()
        elif hasattr(self.teacher_backend, "eval"):
            self.teacher_backend.eval()
        for parameter in getattr(self.teacher_backend, "parameters", lambda: [])():
            parameter.requires_grad = False

    def update(self, student_backend: Any) -> None:
        teacher_state = self.teacher_backend.state_dict()
        student_state = student_backend.state_dict()
        updated = {}
        for key, teacher_value in teacher_state.items():
            student_value = student_state[key]
            if torch.is_tensor(teacher_value):
                updated[key] = self.decay * teacher_value + (1.0 - self.decay) * student_value.detach()
            else:
                updated[key] = student_value
        self.teacher_backend.load_state_dict(updated, strict=False)

    def forward(self, batch: Any) -> Any:
        with torch.no_grad():
            return self.teacher_backend.forward(batch)

    def state_dict(self) -> dict[str, Any]:
        state = self.teacher_backend.state_dict()
        cloned: dict[str, Any] = {}
        for key, value in state.items():
            cloned[key] = value.clone() if torch.is_tensor(value) else copy.deepcopy(value)
        return cloned

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.teacher_backend.load_state_dict(state, strict=False)
