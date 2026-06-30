

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator, ValidationInfo


class MemoryItem(BaseModel):
    id: str
    kind: Literal["fact", "preference", "tool_outcome", "scratchpad"]
    keywords: list[str]
    descriptor: str            # one short human-readable line
    value: dict                # structured payload
    artifact_id: str | None    # handle into the artifact store
    source: str
    run_id: str
    goal_id: str | None
    confidence: float
    created_at: datetime


class Artifact(BaseModel):
    id: int
    content_type: str
    size_bytes: int
    source: str
    descriptor: str


class Goal(BaseModel):
    id: str
    text: str                  # short imperative description
    done: bool
    attach_artifact_id: list[int] = []
    iteration_number_of_completion: str

    @model_validator(mode="after")
    def validate_iteration_completion(self, info: ValidationInfo) -> "Goal":
        context = info.context
        if context and "history_len" in context:
            history_len = context["history_len"]
            val = self.iteration_number_of_completion
            if val is not None and str(val).strip() != "":
                try:
                    iter_num = int(str(val).strip())
                except ValueError:
                    raise ValueError(
                        f"Goal {self.id} has an invalid iteration_number_of_completion: {val!r}. "
                        f"It must be an integer representing a valid iteration number. You passed a"
                        "iteration number without validating it with history of actions executed."
                        "You must always validation if the goal's objectives are solved in that iteration number"
                    )
                if history_len < iter_num:
                    raise ValueError(
                        f"Goal {self.id} has iteration_number_of_completion={iter_num}, "
                        f"but history size is only {history_len}."
                        f" It must be an integer representing a valid iteration number. You passed a"
                        f" iteration number without validating it with history of actions executed."
                        f"You must always validation if the goal's objectives are solved in that iteration number"

                    )
        return self


class HistoryItem(BaseModel):
    iter: int
    kind: Literal["action", "answer"]
    goal_id: str
    text: str | None = None
    tool: str | None = None
    arguments: dict | None = None
    result_descriptor: str | None = None
    artifact_id: int | None = None


class Observation(BaseModel):
    all_done: bool
    goals: list[Goal]

    def next_unfinished(self) -> Goal:
        """Return the first goal that is not done."""
        for g in self.goals:
            if not g.done:
                return g
        raise RuntimeError("No unfinished goals found, but all_done is false.")

class ToolCall(BaseModel):
    name: str
    arguments: dict


class DecisionOutput(BaseModel):
    answer: str | None         # exactly one of these two is populated
    tool_call: ToolCall | None

    @property
    def is_answer(self) -> bool:
        return self.answer is not None