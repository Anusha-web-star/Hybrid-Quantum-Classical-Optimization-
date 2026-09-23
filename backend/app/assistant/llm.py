"""The LLM call. Local only, via Ollama.

Generation runs on this machine and nowhere else. The GRIDOPT dataset, the
solver results and the project documents are assembled into a prompt here and
handed to a model on loopback; none of it leaves the host, and there is no
vendor account, no API key and no per-token cost anywhere in this path.

That is enforced, not just intended: `_endpoint()` refuses any configured host
that is not a loopback address, so pointing `OLLAMA_HOST` at a remote box fails
loudly rather than quietly shipping the project's data off the machine.

There is no HTTP client dependency here on purpose. This is one POST to
127.0.0.1 with a JSON body, which `urllib` in the standard library does
perfectly well - pulling in a client library (or worse, a cloud provider's SDK)
to reach localhost would be pure weight.

Everything provider-specific is confined to this module, behind `generate()`.
The retrieval pipeline, the grounding prompt and the endpoint are unaware of
which model answers, and were not changed to accommodate this one.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Hosts a local model may be reached on. Anything else is refused - see the
#: module docstring. `::1` is IPv6 loopback.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class LLMUnavailable(Exception):
    """No local model can be reached - Ollama is down, or the model is absent.

    Distinct from a call that failed: this is a setup state with a concrete fix,
    and the message always carries the exact command that fixes it.
    """


class LLMError(Exception):
    """The model was reachable but the call did not produce an answer."""


def _endpoint(path: str) -> str:
    """Build an Ollama URL, refusing anything that is not loopback."""
    host = get_settings().ollama_host.rstrip("/")
    parsed = urlparse(host)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LLMUnavailable(
            f"OLLAMA_HOST is not a usable URL ({host!r}). Expected something "
            f"like http://127.0.0.1:11434."
        )

    if parsed.hostname not in LOOPBACK_HOSTS:
        raise LLMUnavailable(
            f"OLLAMA_HOST points at {parsed.hostname!r}, which is not this "
            f"machine. The assistant only talks to a local model: the GRIDOPT "
            f"dataset, solver results and documents must not leave the host. "
            f"Set OLLAMA_HOST to http://127.0.0.1:11434."
        )

    return f"{host}{path}"


def _http_failure(status: int, body: str) -> Exception:
    """Turn an Ollama HTTP error into the right exception, with the fix in it."""
    model = get_settings().assistant_model
    lowered = body.lower()

    # Ollama answers 404 both for "no such model" and for an unknown route. The
    # first is the one that actually happens, and it has a one-line fix.
    if status == 404 and ("not found" in lowered or "try pulling" in lowered):
        return LLMUnavailable(
            f"The model '{model}' is not installed in Ollama. Install it with:"
            f"\n    ollama pull {model}\n"
            f"The backend does not need restarting afterwards."
        )

    logger.warning("Assistant: local model call failed with status %s.", status)
    return LLMError(f"The local model call failed (HTTP {status}).")


def _request(path: str, payload: Optional[dict] = None, timeout: float = 10.0):
    """One JSON call to the local Ollama API. Returns the decoded body."""
    url = _endpoint(path)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - the status alone is enough
            pass
        raise _http_failure(exc.code, body) from exc
    except TimeoutError as exc:
        raise LLMError(
            "The local model did not respond in time. A larger model on CPU can "
            "take a while; raise ASSISTANT_TIMEOUT_S or use a smaller model."
        ) from exc
    except urllib.error.URLError as exc:
        # URLError also wraps socket timeouts on some Python builds, so the
        # timeout case is checked before falling back to "not running".
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise LLMError(
                "The local model did not respond in time. Raise "
                "ASSISTANT_TIMEOUT_S or use a smaller model."
            ) from exc
        raise LLMUnavailable(
            f"Ollama is not reachable at {get_settings().ollama_host}. Start it "
            f"with `ollama serve` (or open the Ollama app), then ask again."
        ) from exc
    except json.JSONDecodeError as exc:
        raise LLMError("Ollama returned a response that could not be read.") from exc


def installed_models() -> list:
    """Model names Ollama currently has, or [] if it cannot be reached."""
    try:
        body = _request("/api/tags", timeout=5.0)
    except (LLMUnavailable, LLMError):
        return []
    return [entry.get("name", "") for entry in body.get("models", []) or []]


def _matches(installed: str, wanted: str) -> bool:
    """Whether an installed tag satisfies the configured model name.

    Ollama reports fully tagged names ("llama3.2:3b"), and a bare "llama3.2"
    resolves to its default tag, so a configured name without a tag is treated
    as matching any tag of the same model.
    """
    if installed == wanted:
        return True
    return ":" not in wanted and installed.split(":")[0] == wanted


def is_configured() -> bool:
    """True when Ollama is up and the configured model is actually installed."""
    wanted = get_settings().assistant_model
    return any(_matches(name, wanted) for name in installed_models())


def generate(system_prompt: str, user_message: str,
             model: Optional[str] = None) -> str:
    """One grounded completion from the local model. Returns the answer text.

    Raises `LLMUnavailable` when there is nothing to call - and the message says
    exactly which command fixes it - and `LLMError` when the call itself failed.
    """
    settings = get_settings()
    chosen = model or settings.assistant_model

    body = _request(
        "/api/chat",
        {
            "model": chosen,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "options": {
                # num_ctx is the single most important setting here. Ollama's
                # default context window is small, and a prompt longer than it
                # is silently TRUNCATED - the retrieved GRIDOPT context would be
                # cut off part-way and the model would answer from whatever
                # survived, with no error anywhere. That is precisely the
                # failure this assistant exists to prevent, so the window is set
                # explicitly, with room for the grounding prompt plus a full
                # context block.
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": settings.assistant_max_tokens,
                # Grounded extraction, not composition. Near-greedy decoding
                # keeps the model quoting the context rather than embellishing
                # it, and makes the same question give the same answer.
                "temperature": settings.ollama_temperature,
                "top_p": 0.9,
                "repeat_penalty": 1.05,
            },
            # Keep the model resident between questions, so the second question
            # in a session does not pay the load cost again.
            "keep_alive": settings.ollama_keep_alive,
        },
        timeout=settings.assistant_timeout_s,
    )

    text = ((body.get("message") or {}).get("content") or "").strip()

    if not text:
        raise LLMError("The local model returned an empty answer.")
    return text
