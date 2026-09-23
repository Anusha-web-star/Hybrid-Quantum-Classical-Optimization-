"""Request and response models for the grounded project assistant.

The response is deliberately more than an answer string: `sources` is what makes
the answer checkable, and `grounded` is what tells the interface whether it is
showing an answer at all.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.assistant.service import MAX_QUESTION_CHARS, MIN_QUESTION_CHARS


class AssistantQuery(BaseModel):
    """A question, and optionally the run the user is looking at."""

    question: str = Field(
        ...,
        min_length=MIN_QUESTION_CHARS,
        max_length=MAX_QUESTION_CHARS,
        description="The question to answer from GRIDOPT project context.",
        examples=["Why did QAOA pick this route over NN?"],
    )
    run: Optional[dict[str, Any]] = Field(
        None,
        description="The optimization run to answer about: the body a previous "
                    "POST /solve/compare returned. Optional. When it is "
                    "absent the assistant has no solver results to read and "
                    "says so rather than describing a run it cannot see. "
                    "Nothing here is stored or added to the shared index.",
    )
    top_k: Optional[int] = Field(
        None, ge=1, le=20,
        description="How many retrieved chunks to consider. Defaults to the "
                    "server's configured value.",
    )


class AssistantSourceOut(BaseModel):
    """One retrieved piece of context that supported the answer."""

    id: str
    kind: str = Field(
        ...,
        description="'dataset' for a transmission-line, station or network "
                    "record; 'doc' for documentation, approved reference "
                    "material or project knowledge; 'code' for a module, class "
                    "or function of this repository; 'solver' for output of "
                    "the attached run.",
    )
    title: str
    locator: str = Field(
        ..., description="Where this came from: CSV row, document heading, or run field."
    )
    score: float = Field(..., description="Retrieval score. Higher is a closer match.")


class AssistantAnswerOut(BaseModel):
    """A grounded answer, the sources behind it, and whether it is grounded."""

    answer: str
    sources: list[AssistantSourceOut]
    grounded: bool = Field(
        ...,
        description="True only when the answer was generated from retrieved "
                    "GRIDOPT context. False means nothing in the project data "
                    "matched the question, and `answer` says so. A missing "
                    "local model is not this case: it is a 503.",
    )
    reason: Optional[str] = Field(
        None,
        description="Why the answer is not grounded. Currently always "
                    "'no_matching_context'. Null when it is grounded.",
    )
    retrieved: int = Field(..., description="Chunks placed in the model's context.")
    used_solver_context: bool = Field(
        ...,
        description="True when an attached run's output was among the sources.",
    )
    model: Optional[str] = Field(
        None, description="The model that produced the answer, when one did."
    )


class AssistantStatusOut(BaseModel):
    """What the assistant can currently do.

    Generation is a local model, so there is no credential in this payload and
    none to withhold - only where the model runs and whether it is installed.
    """

    ready: bool
    model_configured: bool = Field(
        ..., description="True when Ollama is running and the model is pulled."
    )
    model: Optional[str] = None
    runtime: Optional[dict[str, Any]] = Field(
        None,
        description="Where generation runs: provider, loopback host, model, "
                    "whether it is installed, and the `ollama pull` command "
                    "when it is not.",
    )
    chunks: Optional[int] = None
    chunks_by_kind: Optional[dict[str, int]] = None
    top_k: Optional[int] = None
    index: Optional[dict[str, Any]] = None
    retrieval: Optional[str] = None
    message: Optional[str] = None
