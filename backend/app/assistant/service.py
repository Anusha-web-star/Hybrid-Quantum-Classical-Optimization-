"""The RAG pipeline the endpoint calls.

    question
      -> retrieve over the project index (+ this run's context, if attached)
      -> top-k chunks
      -> constrained prompt
      -> grounded answer
      -> the sources that supported it

`grounded` in the result means one thing precisely: the answer was produced from
retrieved GRIDOPT context, and the sources listed are the context the model
read. It is False when retrieval found nothing, and the answer is then the
project's standard unavailable line rather than a guess.

An unavailable local model is NOT that case. It raises
`AssistantNotConfigured`, which the endpoint reports as a 503 setup fault -
because "Ollama is not running here" and "the project data does not cover
that" are different facts with different fixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.assistant import context as context_module
from app.assistant import index as index_module
from app.assistant import llm
from app.assistant.documents import ScoredChunk
from app.assistant.prompts import UNAVAILABLE, SYSTEM_PROMPT, build_user_message
from app.assistant.retrieval import Bm25Retriever, CompositeRetriever
from app.assistant.runcontext import solver_run_chunks
from app.core.config import get_settings

#: Guard rails on the question itself, enforced again here so the service is
#: safe to call from anywhere, not only from behind the request model.
MIN_QUESTION_CHARS = 3
MAX_QUESTION_CHARS = 2000


class InvalidQuestion(Exception):
    """The question cannot be answered as asked."""


class AssistantNotConfigured(Exception):
    """Retrieval worked, but no local model is available to answer with.

    This is deliberately NOT reported as "the GRIDOPT data does not cover that".
    Those are opposite situations: one is a fact about the project's data, the
    other is a fact about this machine's setup, and conflating them sends the
    reader looking for a missing dataset row when the actual fix is one command.
    The retrieval count travels with the error so the message can say plainly
    that the pipeline itself is healthy, and `hint` carries that command.
    """

    def __init__(self, message: str, retrieved: int = 0, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.retrieved = retrieved
        self.hint = hint


@dataclass
class AssistantAnswer:
    """What the endpoint returns, before it is shaped into the response model."""

    answer: str
    sources: list = field(default_factory=list)
    grounded: bool = False
    #: Machine-readable reason when `grounded` is False. None when it is True.
    #: Currently only 'no_matching_context'.
    reason: Optional[str] = None
    retrieved: int = 0
    used_solver_context: bool = False
    model: Optional[str] = None


def validate_question(question: Optional[str]) -> str:
    """Normalise and check a question. Raises `InvalidQuestion`."""
    text = (question or "").strip()
    if len(text) < MIN_QUESTION_CHARS:
        raise InvalidQuestion("Ask a question of at least a few characters.")
    if len(text) > MAX_QUESTION_CHARS:
        raise InvalidQuestion(
            f"That question is too long ({len(text)} characters). "
            f"Keep it under {MAX_QUESTION_CHARS}."
        )
    return text


def setup_hint() -> str:
    """The one command that makes the assistant able to answer, right now.

    Which command depends on what is missing, so it is derived rather than
    hardcoded: a stopped Ollama and an un-pulled model need different fixes.
    """
    settings = get_settings()
    if llm.installed_models():
        return f"ollama pull {settings.assistant_model}"
    return (
        "Start Ollama (run 'ollama serve', or open the Ollama app), then run: "
        f"ollama pull {settings.assistant_model}"
    )


def _source_payload(scored: ScoredChunk) -> dict:
    chunk = scored.chunk
    return {
        "id": chunk.id,
        "kind": chunk.kind,
        "title": chunk.title,
        "locator": chunk.locator,
        "score": scored.score,
    }


def retrieve(question: str, run: Optional[dict] = None,
             top_k: Optional[int] = None) -> list:
    """Top-k chunks for a question, over the index and any attached run.

    Run context is retrieved from a throwaway retriever built per request. That
    is deliberate: an actual run belongs to the caller looking at it, and must
    never be written into the shared index where another question could pick it
    up as if it were project data.
    """
    settings = get_settings()
    knowledge = index_module.get_knowledge_base()

    run_chunks = solver_run_chunks(run) if run else []
    run_retriever = Bm25Retriever(run_chunks) if run_chunks else None

    retriever = CompositeRetriever(knowledge.retriever, run_retriever)
    return retriever.search(question, top_k or settings.assistant_top_k)


def answer_question(question: str, run: Optional[dict] = None,
                    top_k: Optional[int] = None) -> AssistantAnswer:
    """Run the whole pipeline for one question."""
    settings = get_settings()
    text = validate_question(question)
    scored = retrieve(text, run=run, top_k=top_k)

    context_block, used = context_module.assemble(scored)

    # Nothing matched. This is a real answer, not a failure: the honest thing
    # to say is that the project data does not cover it.
    if not used:
        return AssistantAnswer(
            answer=UNAVAILABLE,
            sources=[],
            grounded=False,
            reason="no_matching_context",
            retrieved=0,
        )

    used_solver = any(scored_chunk.chunk.kind == "solver" for scored_chunk in used)
    sources = [_source_payload(scored_chunk) for scored_chunk in used]

    try:
        generated = llm.generate(SYSTEM_PROMPT, build_user_message(text, context_block))
    except llm.LLMUnavailable as exc:
        # Retrieval found context; there is simply no local model to answer
        # with. That is a setup error, not an answer, so it is raised rather
        # than returned - the endpoint turns it into a 503 the interface can
        # show as a configuration problem, with the fixing command attached.
        raise AssistantNotConfigured(
            str(exc), retrieved=len(used), hint=setup_hint(),
        ) from exc

    return AssistantAnswer(
        answer=generated,
        sources=sources,
        grounded=True,
        retrieved=len(used),
        used_solver_context=used_solver,
        model=settings.assistant_model,
    )


def status() -> dict:
    """What the assistant can currently do.

    There is no credential to leak here any more: generation is a local model,
    so the only things worth reporting are whether Ollama is up and whether the
    configured model has been pulled. When it has not, the exact `ollama pull`
    command is part of the response, because that is the whole fix.
    """
    settings = get_settings()
    available = llm.installed_models()
    model_ready = llm.is_configured()

    runtime = {
        "generation": "local",
        "provider": "ollama",
        "host": settings.ollama_host,
        "model": settings.assistant_model,
        "model_installed": model_ready,
        "ollama_running": bool(available),
        "models_installed": available,
        "context_window": settings.ollama_num_ctx,
    }
    if not model_ready:
        runtime["fix"] = (
            f"ollama pull {settings.assistant_model}" if available
            else "Start Ollama (`ollama serve`), then: "
                 f"ollama pull {settings.assistant_model}"
        )

    try:
        knowledge = index_module.get_knowledge_base()
    except Exception as exc:  # the index is a derived artefact; report, don't raise
        return {
            "ready": False,
            "model_configured": model_ready,
            "runtime": runtime,
            "message": str(exc),
        }

    return {
        "ready": True,
        "model_configured": model_ready,
        "model": settings.assistant_model,
        "runtime": runtime,
        "chunks": len(knowledge),
        "chunks_by_kind": knowledge.counts,
        "top_k": settings.assistant_top_k,
        "index": knowledge.manifest,
        "retrieval": "BM25 lexical over the project index (see retrieval.py)",
    }
