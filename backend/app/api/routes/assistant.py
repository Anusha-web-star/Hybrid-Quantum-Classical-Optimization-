"""The grounded project assistant endpoint.

`POST /assistant/query` is the whole surface: a question in, a grounded answer
and its sources out. `GET /assistant/status` reports whether the knowledge base
and a model are available, so the panel can say what is wrong before the user
types a question.

The handler is a plain `def`, so FastAPI runs it on the threadpool and the
model call does not block the event loop. Both routes are mounted behind the
same authentication dependency as the rest of the application in `main.py`.
"""

from fastapi import APIRouter, HTTPException, status

from phase1.data_loader import DatasetError

from app.api import errors
from app.assistant import service
from app.assistant.llm import LLMError
from app.schemas.assistant import (AssistantAnswerOut, AssistantQuery,
                                   AssistantStatusOut)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post(
    "/query",
    response_model=AssistantAnswerOut,
    summary="Ask a grounded question about this GRIDOPT project",
    description="Answers from the project's own context only: the "
                "transmission-line dataset, the project documentation and the "
                "approved tariff reference, plus the optimization run you "
                "attach as `run`.\n\n"
                "The assistant does not use outside knowledge. When the "
                "retrieved context does not support an answer it says the "
                "information is unavailable and returns `grounded: false` "
                "rather than filling the gap.\n\n"
                "`sources` lists exactly the context the model read - a CSV "
                "row for a dataset question, a document heading for a "
                "methodology question, a run field for a solver question.\n\n"
                "Attach `run` to ask about routes, distances, runtimes or "
                "loss costs: it is the body a previous `POST /solve/compare` "
                "returned. Without it there are no solver results to read, and "
                "the assistant will say so instead of inventing a route.",
    responses={
        422: {"description": "The question is missing or unusable."},
        502: {"description": "The model was reachable but the call failed."},
        503: {"description": "Dataset unavailable, or no local model is "
                             "available to generate an answer."},
    },
)
def query_assistant(request: AssistantQuery) -> AssistantAnswerOut:
    try:
        result = service.answer_question(
            request.question, run=request.run, top_k=request.top_k
        )
    except service.InvalidQuestion as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_question", "message": str(exc)},
        ) from exc
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc
    except service.AssistantNotConfigured as exc:
        # Retrieval succeeded and there is no model to answer with. Reported as
        # a configuration fault, never as "the data does not cover that" - the
        # two send the reader to completely different places.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "assistant_not_configured",
                "message": exc.message,
                "retrieved": exc.retrieved,
                "hint": exc.hint,
            },
        ) from exc
    except LLMError as exc:
        # The model was reachable and failed. That is a gateway problem, not an
        # answer - reporting it as one would be the failure this feature exists
        # to prevent.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "assistant_failed", "message": str(exc)},
        ) from exc

    return AssistantAnswerOut(
        answer=result.answer,
        sources=result.sources,
        grounded=result.grounded,
        reason=result.reason,
        retrieved=result.retrieved,
        used_solver_context=result.used_solver_context,
        model=result.model,
    )


@router.get(
    "/status",
    response_model=AssistantStatusOut,
    summary="Whether the assistant is ready, and what it indexed",
    description="Reports the size and provenance of the knowledge base, and "
                "where generation runs - a local Ollama model - including "
                "whether that model has been pulled. There is no credential "
                "in this payload: local generation needs none.",
)
def assistant_status() -> AssistantStatusOut:
    return AssistantStatusOut(**service.status())
