"""The grounded project assistant.

These tests never call a model. `llm.generate` is replaced with a spy that
records the system prompt and the assembled context and returns a fixed string,
so what is exercised is the part this feature owns - retrieval, context
assembly, grounding and source attribution - rather than a vendor's API.

The one thing they do run for real is the solver, through the session-scoped
`compared` fixture: the "no fake solver results" tests are only worth anything
if the run they check is a genuine one.
"""

import json

import pytest

from app.assistant import index as index_module
from app.assistant import llm, service
from app.assistant.prompts import UNAVAILABLE
from app.assistant.runcontext import solver_run_chunks

ANSWER = "A fixed answer, so the test asserts on plumbing rather than prose."


@pytest.fixture
def spy_llm(monkeypatch):
    """Replace the model call with a recorder. Returns the call log."""
    calls = []

    def fake_generate(system_prompt, user_message, model=None):
        calls.append({"system": system_prompt, "user": user_message, "model": model})
        return ANSWER

    monkeypatch.setattr(llm, "generate", fake_generate)
    return calls


@pytest.fixture
def configured(monkeypatch):
    """Report a model as configured without putting a credential anywhere."""
    monkeypatch.setattr(llm, "is_configured", lambda: True)


# ---------------------------------------------------------------------------
# 1. /assistant/query
# ---------------------------------------------------------------------------

def test_query_answers_and_reports_its_sources(client, spy_llm):
    response = client.post(
        "/assistant/query",
        json={"question": "How many stations and transmission lines are in the network?"},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["answer"] == ANSWER
    assert body["grounded"] is True
    assert body["reason"] is None
    assert body["retrieved"] == len(body["sources"]) > 0
    assert body["used_solver_context"] is False


def test_query_requires_a_question(client):
    assert client.post("/assistant/query", json={}).status_code == 422


@pytest.mark.parametrize("question", ["", "  ", "a", "x" * 2001])
def test_query_rejects_unusable_questions(client, question):
    response = client.post("/assistant/query", json={"question": question})
    assert response.status_code == 422


def test_query_rejects_a_non_string_question(client):
    assert client.post(
        "/assistant/query", json={"question": {"text": "hello"}}
    ).status_code == 422


def test_query_is_authenticated(client, monkeypatch):
    """The endpoint sits behind the same gate as the rest of the application.

    Checked in token mode, where the gate has something to reject; the active
    demo mode admits every caller by design (see tests/test_auth.py).
    """
    from app.core.auth import require_user
    from app.core.config import get_settings
    from app.main import app

    monkeypatch.setenv("AUTH_MODE", "supabase")
    get_settings.cache_clear()
    override = app.dependency_overrides.pop(require_user)
    try:
        response = client.post("/assistant/query", json={"question": "What is indexed?"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides[require_user] = override
        get_settings.cache_clear()


def test_status_reports_the_index_without_any_credential(client, configured):
    body = client.get("/assistant/status").json()

    assert body["ready"] is True
    assert body["chunks"] > 0
    assert body["chunks_by_kind"]["dataset"] > 0
    assert body["chunks_by_kind"]["doc"] > 0

    # Nothing in the payload may carry a secret.
    serialized = json.dumps(body).lower()
    assert "api_key" not in serialized
    assert "sk-ant" not in serialized


# ---------------------------------------------------------------------------
# 2. Grounded response behaviour
# ---------------------------------------------------------------------------

def test_the_model_only_ever_sees_retrieved_project_context(client, spy_llm):
    client.post(
        "/assistant/query",
        json={"question": "What voltage is the Kaiga to Kodasalli transmission line?"},
    )
    call = spy_llm[-1]

    assert "===== BEGIN RETRIEVED GRIDOPT CONTEXT =====" in call["user"]
    assert "===== END RETRIEVED GRIDOPT CONTEXT =====" in call["user"]
    assert call["user"].rstrip().endswith(
        "Question: What voltage is the Kaiga to Kodasalli transmission line?"
    )


def test_the_system_prompt_carries_every_grounding_rule(client, spy_llm):
    client.post("/assistant/query", json={"question": "What does GRIDOPT optimize?"})
    system = spy_llm[-1]["system"]

    assert "Answer ONLY using the supplied retrieved GRIDOPT context" in system
    assert "Do not invent facts" in system
    assert UNAVAILABLE in system
    assert "energy-charge-only" in system
    assert "continuous modeled operation" in system
    assert "quantum advantage" in system
    # The one data-semantics trap this project must not fall into.
    assert "less energy loss" in system


def test_the_prompt_forbids_calculating_figures(client, spy_llm):
    """A regression guard, from a real failure.

    A small local model, given a dataset row AND the formula that produced its
    rupee columns, applied the formula itself - substituting Distance_km for
    Energy_Loss_MW - and reported a confidently wrong loss cost instead of the
    one printed in the row it had been handed. Quoting rules alone were not
    enough; the prohibition has to be explicit and absolute.
    """
    client.post("/assistant/query", json={"question": "What is the loss cost?"})
    system = spy_llm[-1]["system"]

    assert "NEVER CALCULATE A FIGURE" in system
    assert "must appear verbatim in the retrieved context" in system
    assert "A calculated number is a fabricated number" in system
    # And it must say why the formula being visible is not permission to use it.
    assert "not for you to apply" in system


def test_the_prompt_forbids_guessing_an_unmatched_name(client, spy_llm):
    client.post("/assistant/query", json={"question": "What is the loss cost?"})
    system = spy_llm[-1]["system"]

    assert "do not guess which one it means" in system


def test_the_objective_context_states_distance_is_not_energy(client, spy_llm):
    """A question about energy optimization must retrieve the correct answer."""
    client.post(
        "/assistant/query",
        json={"question": "Does GRIDOPT directly optimize energy loss?"},
    )
    context = spy_llm[-1]["user"]

    assert "route-distance objective" in context
    assert "Neither solver optimizes energy loss" in context
    assert "energy-aware optimization objective would require" in context


def test_monetary_context_carries_the_projects_own_tariff_basis(client, spy_llm):
    from energy_cost.tariff import KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE as tariff

    client.post(
        "/assistant/query",
        json={"question": "How is the annual loss cost in rupees calculated?"},
    )
    context = spy_llm[-1]["user"]

    assert f"{tariff.inr_per_kwh:.2f}" in context
    assert "8760" in context
    assert "ENERGY CHARGE ONLY" in context
    assert "continuous modeled operation" in context


def test_a_failed_model_call_is_a_gateway_error_not_an_answer(client, monkeypatch):
    def explode(system_prompt, user_message, model=None):
        raise llm.LLMError("The assistant's model call failed (HTTP 500).")

    monkeypatch.setattr(llm, "generate", explode)
    response = client.post(
        "/assistant/query",
        json={"question": "How many transmission lines are in the network?"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "assistant_failed"


# ---------------------------------------------------------------------------
# 3. Unavailable-information behaviour
# ---------------------------------------------------------------------------

def test_an_off_topic_question_gets_the_projects_unavailable_line(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "Who won the 2019 cricket world cup final?"},
    ).json()

    assert body["answer"] == UNAVAILABLE
    assert body["grounded"] is False
    assert body["reason"] == "no_matching_context"
    assert body["sources"] == []
    # Nothing was sent to the model at all - there was nothing to ground on.
    assert spy_llm == []


def test_without_a_run_no_solver_context_exists(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "What was the total route distance of the hybrid QAOA run?"},
    ).json()

    assert body["used_solver_context"] is False
    assert all(source["kind"] != "solver" for source in body["sources"])
    if spy_llm:
        assert "ACTUAL SOLVER RUN OUTPUT" not in spy_llm[-1]["user"]


def test_an_unavailable_local_model_is_a_setup_error_not_a_data_gap(
    client, monkeypatch
):
    """The two must never be confused.

    "No model on this machine" and "the project data does not cover that" have
    different fixes. Reporting the first as the second is what made the panel
    claim every question was unanswerable while retrieval was working perfectly.
    """
    def unavailable(system_prompt, user_message, model=None):
        raise llm.LLMUnavailable("The model is not installed in Ollama.")

    monkeypatch.setattr(llm, "generate", unavailable)
    response = client.post(
        "/assistant/query", json={"question": "How many stations are there?"}
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "assistant_not_configured"
    # The hint must be a command the reader can actually run.
    assert "ollama" in detail["hint"].lower()
    # The error must say retrieval worked - that is the whole distinction.
    assert detail["retrieved"] > 0
    # And it must not borrow the data-gap wording.
    assert UNAVAILABLE not in detail["message"]


def test_a_stopped_runtime_and_a_missing_model_give_different_hints(monkeypatch):
    """One command each, and never the wrong one."""
    monkeypatch.setattr(llm, "installed_models", lambda: [])
    stopped = service.setup_hint()

    monkeypatch.setattr(llm, "installed_models", lambda: ["something-else:1b"])
    missing_model = service.setup_hint()

    assert "ollama serve" in stopped
    assert "ollama serve" not in missing_model
    assert missing_model.startswith("ollama pull ")


# ---------------------------------------------------------------------------
# 3b. The local model layer: no cloud, no credential, no silent truncation
# ---------------------------------------------------------------------------

def test_generation_is_local_only_and_refuses_a_remote_host(monkeypatch):
    """A remote host must fail loudly, not ship the dataset off the machine."""
    from app.core.config import get_settings

    monkeypatch.setenv("OLLAMA_HOST", "http://models.example.com:11434")
    get_settings.cache_clear()
    try:
        with pytest.raises(llm.LLMUnavailable) as caught:
            llm.generate("system", "user")
        message = str(caught.value)
        assert "not this machine" in message
        assert "must not leave the host" in message
    finally:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        get_settings.cache_clear()


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434",
                                  "http://localhost:11434"])
def test_loopback_hosts_are_accepted(monkeypatch, host):
    from app.core.config import get_settings

    monkeypatch.setenv("OLLAMA_HOST", host)
    get_settings.cache_clear()
    try:
        assert llm._endpoint("/api/chat").startswith(host)
    finally:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        get_settings.cache_clear()


def test_the_request_sets_a_context_window_large_enough_for_the_prompt(monkeypatch):
    """Ollama truncates an over-long prompt silently.

    That is the one failure mode that would quietly defeat the whole feature:
    the retrieved GRIDOPT context would be cut off, the model would answer from
    the remainder, and nothing anywhere would report it. So `num_ctx` must be
    sent explicitly, and it must exceed what this pipeline can actually produce.
    """
    from app.assistant import context as context_module
    from app.core.config import get_settings

    sent = {}

    def capture(path, payload=None, timeout=10.0):
        sent["path"] = path
        sent["payload"] = payload
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(llm, "_request", capture)
    llm.generate("system prompt", "user message")

    assert sent["path"] == "/api/chat"
    options = sent["payload"]["options"]
    num_ctx = options["num_ctx"]

    # Worst case the pipeline can hand over: the full context budget plus the
    # grounding prompt, at a conservative 3 characters per token.
    from app.assistant.prompts import SYSTEM_PROMPT
    worst_case_chars = context_module.CONTEXT_BUDGET_CHARS + len(SYSTEM_PROMPT) + 2000
    assert num_ctx > worst_case_chars / 3, (
        f"num_ctx={num_ctx} is too small for a {worst_case_chars}-char prompt; "
        "Ollama would truncate the retrieved context without saying so."
    )
    assert num_ctx == get_settings().ollama_num_ctx


def test_generation_is_near_greedy_so_answers_are_reproducible(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        llm, "_request",
        lambda path, payload=None, timeout=10.0: (
            sent.update(payload=payload) or {"message": {"content": "ok"}}
        ),
    )
    llm.generate("system", "user")

    assert sent["payload"]["options"]["temperature"] <= 0.2
    assert sent["payload"]["stream"] is False


def test_the_grounding_prompt_is_sent_as_the_system_role(monkeypatch):
    """The strict prompt must keep its authority, not be folded into the user turn."""
    sent = {}
    monkeypatch.setattr(
        llm, "_request",
        lambda path, payload=None, timeout=10.0: (
            sent.update(payload=payload) or {"message": {"content": "ok"}}
        ),
    )
    llm.generate("THE GROUNDING RULES", "THE QUESTION")

    messages = sent["payload"]["messages"]
    assert messages[0] == {"role": "system", "content": "THE GROUNDING RULES"}
    assert messages[1] == {"role": "user", "content": "THE QUESTION"}


def test_an_empty_local_answer_is_an_error_not_an_answer(monkeypatch):
    monkeypatch.setattr(
        llm, "_request",
        lambda path, payload=None, timeout=10.0: {"message": {"content": "   "}},
    )
    with pytest.raises(llm.LLMError):
        llm.generate("system", "user")


def test_a_missing_model_names_the_exact_pull_command():
    from app.core.config import get_settings

    failure = llm._http_failure(404, '{"error":"model not found, try pulling it"}')
    assert isinstance(failure, llm.LLMUnavailable)
    assert f"ollama pull {get_settings().assistant_model}" in str(failure)


def test_no_response_can_carry_a_secret(client, monkeypatch):
    """There is no credential in this path at all - and nothing may leak one."""
    monkeypatch.setattr(
        llm, "generate",
        lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("no model")),
    )
    response = client.post(
        "/assistant/query", json={"question": "How many stations are there?"}
    )

    serialized = response.text.lower()
    for marker in ("sk-ant", "api_key", "apikey", "authorization", "bearer"):
        assert marker not in serialized


def test_no_cloud_provider_is_reachable_from_the_assistant_package():
    """The whole point of this change: nothing here can call out to a vendor."""
    import pathlib

    package = pathlib.Path(llm.__file__).parent
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "import anthropic" not in text
        assert "import openai" not in text
        assert "api.anthropic.com" not in text
        assert "api.openai.com" not in text


def test_the_mandatory_money_caveats_survive_chunk_truncation():
    """A chunk longer than the cap loses its END. The caveats must not be there.

    From a real regression: the tariff record led with its citation and put the
    two things the assistant is required to say about money after it. Tightening
    the cap for latency then cut "annualized values assume continuous modeled
    operation" in half - removing a mandatory caveat while leaving the rupee
    figures intact, which is the worst half to keep.
    """
    from app.assistant.context import MAX_CHUNK_CHARS
    from app.assistant.sources import tariff_chunk

    survives = tariff_chunk().text[:MAX_CHUNK_CHARS]

    assert "ENERGY CHARGE ONLY" in survives
    assert "continuous modeled operation" in survives
    assert "not an electricity bill" in survives
    assert "8760" in survives


def test_the_dataset_standing_caveat_is_stated_once_not_per_record(client, spy_llm):
    """Hoisted out of every line chunk for latency - but it must still be said.

    38 line records each carried the same 645-character caveat. Retrieving four
    of them paid for it four times, which on a local CPU model is seconds of
    prompt processing. It now appears once per request instead - so the rule has
    to be verifiably present, and verifiably not duplicated.
    """
    client.post(
        "/assistant/query",
        json={"question": "What is the Energy_Loss_MW of the Kaiga to Kodasalli line?"},
    )
    context = spy_llm[-1]["user"]

    assert "SOURCE columns" in context
    assert "DERIVED columns" in context
    assert "crossing a line twice does not double it" in context
    assert context.count("HOW TO READ THE DATASET RECORDS BELOW") == 1


def test_a_doc_only_answer_carries_no_dataset_preamble(client, spy_llm):
    """The preamble is charged to the budget, so it appears only when it applies."""
    client.post(
        "/assistant/query",
        json={"question": "How does the hybrid QAOA reoptimization loop work?"},
    )
    context = spy_llm[-1]["user"]
    sources_are_docs = "PROJECT DATASET RECORD" not in context

    if sources_are_docs:
        assert "HOW TO READ THE DATASET RECORDS BELOW" not in context


def test_retrieval_is_fast_enough_to_be_irrelevant_to_latency():
    """Retrieval was measured at 0.05ms; generation at tens of seconds.

    This guards the diagnosis, not a micro-benchmark: if retrieval ever becomes
    a meaningful share of the wait, the tuning in context.py is reasoning from a
    premise that no longer holds.
    """
    import time

    service.retrieve("warm up the index")
    t0 = time.perf_counter()
    for _ in range(20):
        service.retrieve("What is the loss cost of the Raichur to Bellary line?")
    per_call = (time.perf_counter() - t0) / 20

    assert per_call < 0.05, f"retrieval took {per_call*1000:.1f}ms per call"


# ---------------------------------------------------------------------------
# 4. Retrieval
# ---------------------------------------------------------------------------

def test_the_index_covers_every_line_and_every_station():
    from app.dataio.network import get_dataset, get_network

    knowledge = index_module.get_knowledge_base()
    dataset, network = get_dataset(), get_network()

    line_chunks = [c for c in knowledge.chunks if c.id.startswith("line:")]
    station_chunks = [c for c in knowledge.chunks if c.id.startswith("station:")]

    assert len(line_chunks) == len(dataset.connections)
    assert len(station_chunks) == len(network.names)
    assert any(c.id == "network:summary" for c in knowledge.chunks)
    assert any(c.id == "reference:tariff" for c in knowledge.chunks)


def test_a_line_question_retrieves_that_lines_own_record():
    found = service.retrieve(
        "What is the distance of the Kaiga Nuclear Power Station to "
        "Kodasalli Power House transmission line?"
    )

    assert found[0].chunk.kind == "dataset"
    # The line's own CSV record has to be in front of the model. Whether the
    # two stations' records outrank it does not matter - they carry the same
    # figure - but the record itself must not be missing.
    assert any(
        chunk.chunk.id == "line:kaiga-nuclear-power-station--kodasalli-power-house"
        for chunk in found
    ), [chunk.chunk.id for chunk in found]


def test_a_methodology_question_retrieves_documentation():
    found = service.retrieve("How does the hybrid QAOA approach work?")
    assert any(scored.chunk.kind == "doc" for scored in found[:3])


def test_retrieval_returns_nothing_for_an_unrelated_question():
    assert service.retrieve("What is the boiling point of mercury on Venus?") == []


def test_retrieved_values_match_the_csv_exactly():
    """A dataset chunk must quote the file, not a rounded or restated version."""
    from app.dataio.network import get_dataset

    dataset = get_dataset()
    connection = next(
        c for c in dataset.connections if c.energy_loss_mw is not None
    )
    found = service.retrieve(
        f"{connection.source} to {connection.destination} "
        f"Energy_Loss_MW and Distance_km"
    )
    line_chunk = next(
        scored.chunk for scored in found if scored.chunk.id.startswith("line:")
    )
    text = line_chunk.text

    assert f"{connection.distance_km:,.3f}".rstrip("0").rstrip(".") in text
    assert f"{connection.energy_loss_mw:,.3f}".rstrip("0").rstrip(".") in text


def test_reindexing_reproduces_the_same_chunk_ids(tmp_path):
    """The index is derived, so rebuilding it must be a no-op in content."""
    before = [chunk.id for chunk in index_module.get_knowledge_base().chunks]
    rebuilt, written = index_module.reindex(tmp_path / "index.json")

    assert written.is_file()
    assert [chunk.id for chunk in rebuilt.chunks] == before

    reloaded = index_module.load(tmp_path / "index.json")
    assert [chunk.id for chunk in reloaded.chunks] == before


# ---------------------------------------------------------------------------
# 5. Source attribution
# ---------------------------------------------------------------------------

def test_every_source_names_where_it_came_from(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "What is the capacity of the Raichur to Bellary line?"},
    ).json()

    assert body["sources"]
    for source in body["sources"]:
        assert source["kind"] in {"dataset", "doc", "solver"}
        assert source["title"].strip()
        assert source["locator"].strip()
        assert source["score"] > 0


def test_a_dataset_question_cites_the_csv_row(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "What is the voltage of the Kaiga to Kodasalli line?"},
    ).json()
    top = body["sources"][0]

    assert top["kind"] == "dataset"
    assert "row" in top["locator"]


def test_a_methodology_question_cites_a_document(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "How does the hybrid QAOA reoptimization loop work?"},
    ).json()

    assert any(source["kind"] == "doc" for source in body["sources"])


def test_reported_sources_are_exactly_what_the_model_read(client, spy_llm):
    body = client.post(
        "/assistant/query",
        json={"question": "What tariff is used to price the modeled losses?"},
    ).json()
    context = spy_llm[-1]["user"]

    assert len(body["sources"]) == context.count("--- SOURCE ")
    for source in body["sources"]:
        assert source["title"] in context
        assert source["locator"] in context


# ---------------------------------------------------------------------------
# 6. No fake solver results
# ---------------------------------------------------------------------------

def test_an_absent_run_produces_no_solver_chunks():
    assert solver_run_chunks({}) == []
    assert solver_run_chunks(None) == []


def test_a_partial_run_reports_gaps_instead_of_filling_them():
    chunks = solver_run_chunks({"start": "Mysuru Substation", "classical": {}})
    text = "\n".join(chunk.text for chunk in chunks)

    assert chunks, "a run with a start is still worth describing"
    assert "not present in the supplied run output" in text
    # No distance, runtime or window was conjured for the missing sections.
    assert "km\n" not in text.replace("not present in the supplied run output", "")


def test_solver_chunks_quote_the_real_run(compared):
    chunks = {chunk.id: chunk for chunk in solver_run_chunks(compared)}
    routes = chunks["run:routes"].text
    comparison = chunks["run:comparison"].text
    detail = chunks["run:hybrid-detail"].text

    nn_km = compared["classical"]["tour"]["total_distance_km"]
    hybrid_km = compared["hybrid"]["tour"]["total_distance_km"]

    assert f"{nn_km:,.3f}".rstrip("0").rstrip(".") in routes
    assert f"{hybrid_km:,.3f}".rstrip("0").rstrip(".") in routes
    assert compared["comparison"]["winner"] in comparison
    assert str(compared["hybrid"]["detail"]["window"]) in detail
    assert compared["hybrid"]["detail"]["backend"] in detail


def test_a_run_question_answers_from_that_runs_own_output(client, spy_llm, compared):
    body = client.post(
        "/assistant/query",
        json={
            "question": "What total route distance did the hybrid QAOA run "
                        "produce, and how does it compare with NN?",
            "run": compared,
        },
    ).json()

    assert body["grounded"] is True
    assert body["used_solver_context"] is True
    assert any(source["kind"] == "solver" for source in body["sources"])

    context = spy_llm[-1]["user"]
    hybrid_km = compared["hybrid"]["tour"]["total_distance_km"]
    assert f"{hybrid_km:,.3f}".rstrip("0").rstrip(".") in context


def test_run_context_is_never_written_into_the_shared_index(client, spy_llm, compared):
    """One caller's run must not leak into another caller's retrieval."""
    client.post(
        "/assistant/query",
        json={"question": "What was the hybrid route distance?", "run": compared},
    )

    knowledge = index_module.get_knowledge_base()
    assert all(chunk.kind != "solver" for chunk in knowledge.chunks)

    body = client.post(
        "/assistant/query",
        json={"question": "What was the hybrid route distance?"},
    ).json()
    assert body["used_solver_context"] is False


def test_run_context_never_claims_quantum_advantage(compared):
    text = "\n".join(chunk.text for chunk in solver_run_chunks(compared))

    assert "not on its own establish quantum advantage" in text
    assert "It is not an energy saving" in text


def test_energy_context_marks_the_annual_figure_as_an_estimate(compared):
    chunks = {chunk.id: chunk for chunk in solver_run_chunks(compared)}
    energy = chunks["run:energy"].text

    assert "not an electricity bill" in energy
    assert "Neither solver optimized for energy loss" in energy
    assert str(compared["energy"]["hours_per_year"]) in energy


# ---------------------------------------------------------------------------
# 7. Project knowledge: the questions a viva actually asks
# ---------------------------------------------------------------------------
#
# These are the tests this whole knowledge layer exists for. The failure they
# guard against is not a wrong answer - it is the assistant saying "I don't have
# enough information" about its own project, which it did for every question
# below before the primer and the source-code layer were indexed.
#
# They assert on the assembled CONTEXT rather than on generated prose: what this
# project controls is what the model is given, and a fixed-string spy stands in
# for the model everywhere else in this file for exactly that reason.

VIVA_CASES = [
    ("What is RAG?",
     ["retrieval-augmented generation", "retrieve"]),
    ("Why did QAOA pick this route over NN?",
     ["strictly shorter", "nearest neighbour", "spliced"]),
    ("Why are 625 qubits required?",
     ["625", "25^2"]),
    ("Why is the annualized loss cost so large?",
     ["8760", "energy charge only"]),
    ("Are you optimizing energy loss?",
     ["neither solver optimizes energy loss", "evaluat"]),
    ("What is Hybrid QAOA?",
     ["window", "nearest neighbour", "qaoa"]),
    ("Why did you use Ollama?",
     ["ollama", "local"]),
    ("What does Energy_Loss_MW mean?",
     ["energy_loss_mw", "distinct"]),
]


@pytest.mark.parametrize("question,expected", VIVA_CASES,
                         ids=[case[0] for case in VIVA_CASES])
def test_a_viva_question_retrieves_the_knowledge_that_answers_it(question, expected):
    from app.assistant import context as context_module

    block, used = context_module.assemble(service.retrieve(question))
    assert used, f"nothing retrieved for {question!r}"

    lowered = block.lower()
    missing = [phrase for phrase in expected if phrase not in lowered]
    assert not missing, (
        f"{question!r} retrieved context without {missing}; "
        f"got {[scored.chunk.id for scored in used]}"
    )


@pytest.mark.parametrize("question,expected", VIVA_CASES,
                         ids=[case[0] for case in VIVA_CASES])
def test_a_viva_question_is_answered_not_refused(client, spy_llm, question, expected):
    """The endpoint must reach the model, not return the unavailable line."""
    body = client.post("/assistant/query", json={"question": question}).json()

    assert body["grounded"] is True, question
    assert body["answer"] != UNAVAILABLE
    assert body["sources"], question
    assert spy_llm, "the model was never called, so nothing was answered"


def test_the_answering_policy_permits_explaining_the_implementation(client, spy_llm):
    """The prompt has to say that describing what the code does IS answering.

    Retrieval alone did not fix the refusals: a strict "answer only from the
    context" instruction, with implementation in the context, still invited a
    refusal because no document stated the conclusion in so many words.
    """
    client.post("/assistant/query", json={"question": "Why did QAOA pick this route over NN?"})
    system = spy_llm[-1]["system"]

    assert "ANSWER WHENEVER THE CONTEXT SUPPORTS AN ANSWER" in system
    assert "Explaining what the implementation does IS answering" in system
    assert "logical consequence" in system
    # And the refusal must stay available for what genuinely is not covered.
    assert UNAVAILABLE in system


def test_the_prompt_forbids_attributing_intent_to_the_algorithm(client, spy_llm):
    """"QAOA understood that this route was better" is the failure to prevent."""
    client.post("/assistant/query", json={"question": "Why is the hybrid route shorter?"})
    system = spy_llm[-1]["system"]

    assert "never what the algorithm wanted" in system
    assert "the acceptance test is the reason" in system.lower()
    assert "never call a route optimal" in system


@pytest.mark.parametrize("question", [
    "Who won the 2019 cricket world cup final?",
    "What is the boiling point of mercury on Venus?",
    "Give me a recipe for bisi bele bath.",
])
def test_a_genuinely_unsupported_question_is_still_refused(client, spy_llm, question):
    """The policy was loosened, not removed. Off-topic still returns grounded=false."""
    body = client.post("/assistant/query", json={"question": question}).json()

    assert body["grounded"] is False, question
    assert body["answer"] == UNAVAILABLE
    assert body["sources"] == []
    assert body["reason"] == "no_matching_context"
    assert spy_llm == [], "the model must not be called with no context"


def test_run_specific_facts_are_not_answered_without_a_run(client, spy_llm):
    """Knowing HOW the loop works must not become claiming what a run produced."""
    body = client.post(
        "/assistant/query",
        json={"question": "How many improvements were accepted in this run?"},
    ).json()

    assert body["used_solver_context"] is False
    if spy_llm:
        system = spy_llm[-1]["system"]
        assert "Never describe a run that is not there" in system
        assert "ACTUAL SOLVER RUN OUTPUT" not in spy_llm[-1]["user"]


def test_with_a_run_attached_the_same_question_reads_that_run(client, spy_llm, compared):
    """The current-run context still wins its slots for a run question."""
    body = client.post(
        "/assistant/query",
        json={"question": "Why did QAOA pick this route over NN in this run?",
              "run": compared},
    ).json()

    assert body["grounded"] is True
    assert body["used_solver_context"] is True
    context = spy_llm[-1]["user"]
    assert "ACTUAL SOLVER RUN OUTPUT" in context
    # And the mechanism is in front of the model alongside the run's numbers.
    assert "hybrid" in context.lower()


# ---------------------------------------------------------------------------
# 8. The source-code knowledge layer
# ---------------------------------------------------------------------------

def test_every_allowlisted_source_file_is_indexed():
    from app.assistant.code import CODE_SOURCES, code_chunks

    chunks, missing = code_chunks()
    assert missing == [], f"allowlisted files that are not on disk: {missing}"

    indexed = {chunk.metadata["file"] for chunk in chunks}
    listed = {relative for relative, _label in CODE_SOURCES}
    assert indexed == listed


def test_code_chunks_carry_real_functions_from_the_real_files():
    knowledge = index_module.get_knowledge_base()
    by_id = {chunk.id: chunk for chunk in knowledge.chunks}

    # The acceptance test that answers "why is the hybrid route shorter".
    hybrid = by_id.get("code:phase2-hybrid-py:hybrid_solve")
    assert hybrid is not None, "the hybrid solver's own function is not indexed"
    assert hybrid.kind == "code"
    assert "def hybrid_solve" in hybrid.text
    assert hybrid.locator.startswith("phase2/hybrid.py lines ")

    # And the classical baseline it starts from.
    assert "code:phase1-nn-tsp-py:solve" in by_id


def test_a_code_question_retrieves_the_implementation():
    found = service.retrieve(
        "How does reoptimize_window build the QUBO for a window of the tour?"
    )
    assert any(scored.chunk.kind == "code" for scored in found), [
        scored.chunk.id for scored in found
    ]


def test_the_knowledge_base_indexes_all_four_families():
    counts = index_module.get_knowledge_base().counts

    assert counts.get("dataset", 0) > 0
    assert counts.get("doc", 0) > 0
    assert counts.get("code", 0) > 0
    # 'solver' is per request and must never be in the shared index.
    assert "solver" not in counts


def test_the_ingestion_modules_index_what_they_produce_but_not_themselves():
    """primer.py and code.py list every topic and every filename in the project.

    As chunks they match almost any question and crowd out the chunk that
    actually answers it - which is exactly what they did when first indexed.
    """
    from app.assistant.code import CODE_SOURCES

    listed = {relative for relative, _label in CODE_SOURCES}
    assert "backend/app/assistant/primer.py" not in listed
    assert "backend/app/assistant/code.py" not in listed


# ---------------------------------------------------------------------------
# 9. Nothing indexed may carry a secret
# ---------------------------------------------------------------------------

def test_no_env_file_is_anywhere_on_the_allowlist():
    from app.assistant.code import CODE_SOURCES

    for relative, _label in CODE_SOURCES:
        assert ".env" not in relative
        assert "credential" not in relative.lower() or relative.endswith(".py")
    # seed.sql is 38 rows of the CSV restated; the CSV is already indexed.
    assert all(not relative.endswith("seed.sql") for relative, _ in CODE_SOURCES)


def test_no_value_from_the_real_env_file_appears_in_the_index():
    """The strongest form of the check: the project's own secrets, verbatim.

    Reads the git-ignored .env if it exists and asserts that none of its values
    can be found in any indexed chunk. Nothing is printed, so a failure names the
    variable, never the value.
    """
    from pathlib import Path

    from app.assistant.code import PROJECT_ROOT

    env_file = Path(PROJECT_ROOT) / ".env"
    if not env_file.is_file():
        pytest.skip("no .env in this checkout")

    secrets = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if len(value) >= 8:
            secrets[name.strip()] = value

    assert secrets, "expected the .env to hold at least one value to check against"

    corpus = "\n".join(chunk.text for chunk in index_module.get_knowledge_base().chunks)
    leaked = [name for name, value in secrets.items() if value in corpus]
    assert leaked == [], f"indexed chunks contain the value of: {leaked}"


def test_an_assigned_secret_is_redacted_before_it_can_be_indexed():
    from app.assistant.code import redact

    blanked = redact('api_key = "abcdef123456"')
    assert "abcdef123456" not in blanked
    assert "api_key" in blanked

    blanked = redact("IBM_QUANTUM_TOKEN=abcdef123456")
    # The NAME stays - "the token is read from IBM_QUANTUM_TOKEN" is a fact
    # worth answering - while the value goes.
    assert "IBM_QUANTUM_TOKEN" in blanked
    assert "abcdef123456" not in blanked


# ---------------------------------------------------------------------------
# 10. The index stays derived, deterministic and reproducible
# ---------------------------------------------------------------------------

def test_rebuilding_the_index_is_byte_for_byte_identical(tmp_path):
    """Deleting the index must cost nothing, so two builds must agree exactly."""
    first = index_module.build()
    second = index_module.build()

    assert [chunk.to_dict() for chunk in first.chunks] == [
        chunk.to_dict() for chunk in second.chunks
    ]


def test_every_primer_entry_declares_the_questions_it_answers():
    """An entry with no question forms is an entry retrieval cannot find."""
    from app.assistant.primer import ASKED_AS, ENTRIES

    slugs = [slug for slug, _title, _locator, _body in ENTRIES]
    assert sorted(slugs) == sorted(set(slugs)), "duplicate primer slug"
    assert set(slugs) == set(ASKED_AS), (
        f"entries without question forms: {set(slugs) - set(ASKED_AS)}; "
        f"question forms without an entry: {set(ASKED_AS) - set(slugs)}"
    )


def test_the_reindex_command_reports_the_code_layer(tmp_path, capsys):
    from app.assistant.reindex import main

    assert main(["--out", str(tmp_path / "index.json")]) == 0
    printed = capsys.readouterr().out

    assert "code" in printed
    assert "source files" in printed
    assert (tmp_path / "index.json").is_file()


def test_stemming_matches_a_questions_word_form_to_the_corpus():
    from app.assistant.retrieval import tokenize

    assert tokenize("qubits") == tokenize("qubit")
    assert tokenize("rupees") == tokenize("rupee")
    assert tokenize("optimizing") == tokenize("optimize")
    # And it must not maul short words into each other.
    assert tokenize("loss") == ["loss"]
    assert tokenize("lines") != tokenize("line cost")


# ---------------------------------------------------------------------------
# 11. Current-run questions
# ---------------------------------------------------------------------------
#
# The bug these guard against, in full, because all three parts of it looked
# correct on their own:
#
#   1. `CompositeRetriever` reserved retrieval slots for the attached run, and
#      `context.assemble` then spent the whole character budget in pure score
#      order - so the run was retrieved and never reached the model.
#   2. The run's energy figures were one 3,400-character chunk against a
#      1,400-character per-chunk cap, so the tariff, the annualisation note and
#      the caveats were cut off even when it did get in.
#   3. Run chunks are scored over a ten-chunk corpus where "hybrid" and
#      "distance" appear everywhere and score ~0, which put them under a floor
#      calibrated on the 357-chunk index.
#
# The user-visible symptom of all three was the same: "What's the estimated
# annual loss cost for this run?" answered with "I don't have enough
# information in the available GRIDOPT data".

RUN_QUESTIONS = [
    "What's the estimated annual loss cost for this run?",
    "What's the hybrid modeled loss?",
    "What's the NN modeled loss?",
    "How much does the loss cost per hour?",
    "Why is the annualized cost so high?",
    "Why did QAOA pick this route over NN?",
    "How much shorter is the hybrid route?",
    "How many qubits were used?",
]


@pytest.mark.parametrize("question", RUN_QUESTIONS, ids=RUN_QUESTIONS)
def test_a_current_run_question_reaches_the_model_with_the_run(
    client, spy_llm, compared, question,
):
    body = client.post(
        "/assistant/query", json={"question": question, "run": compared},
    ).json()

    assert body["answer"] != UNAVAILABLE, question
    assert body["grounded"] is True, question
    assert body["used_solver_context"] is True, (
        f"{question!r} answered without the run: "
        f"{[source['id'] for source in body['sources']]}"
    )
    assert "ACTUAL SOLVER RUN OUTPUT" in spy_llm[-1]["user"]


def test_the_annual_loss_cost_question_sees_this_runs_own_figure(
    client, spy_llm, compared,
):
    """The reported bug, end to end, on a genuine run."""
    hybrid = compared["energy"]["hybrid"]

    client.post(
        "/assistant/query",
        json={"question": "What's the estimated annual loss cost for this run?",
              "run": compared},
    )
    context = spy_llm[-1]["user"]

    # The run's own annual figure, formatted exactly as the chunk prints it.
    annual = f"{hybrid['loss_cost_per_year_inr']:,.2f}".rstrip("0").rstrip(".")
    assert annual in context
    # With the rate it was costed at, and the assumption behind the number.
    assert str(compared["energy"]["tariff"]["inr_per_kwh"]) in context
    assert "8,760" in context or "8760" in context
    assert "not an electricity bill" in context


def test_each_routes_modeled_loss_is_retrievable_on_its_own(compared):
    """"The hybrid modeled loss" and "the NN modeled loss" are different asks."""
    chunks = {chunk.id: chunk for chunk in solver_run_chunks(compared)}

    for key, chunk_id in (("classical", "run:energy:classical"),
                          ("hybrid", "run:energy:hybrid")):
        route = compared["energy"][key]
        text = chunks[chunk_id].text
        loss = f"{route['total_energy_loss_mw']:,.3f}".rstrip("0").rstrip(".")
        assert loss in text, chunk_id
        assert "not an electricity bill" in text, chunk_id
        assert str(compared["energy"]["tariff"]["inr_per_kwh"]) in text, chunk_id


def test_every_run_money_figure_carries_its_indian_scale(compared):
    """lakh / crore are computed here, from the run - the model never divides."""
    from app.assistant.runcontext import _indian_scale

    hybrid = compared["energy"]["hybrid"]
    text = {chunk.id: chunk.text for chunk in solver_run_chunks(compared)}

    hourly = _indian_scale(hybrid["loss_cost_per_hour_inr"]).strip(" ()")
    annual = _indian_scale(hybrid["loss_cost_per_year_inr"]).strip(" ()")

    assert "lakh" in hourly or "crore" in hourly
    assert "crore" in annual
    assert hourly in text["run:energy:hybrid"]
    assert annual in text["run:energy:hybrid"]


def test_the_indian_scale_is_derived_never_hardcoded():
    from app.assistant.runcontext import _indian_scale

    assert _indian_scale(3_232_897.80) == " (about Rs. 32.33 lakh)"
    assert _indian_scale(28_320_184_728) == " (about Rs. 2,832.02 crore)"
    # Small change and absent values stay plain rather than being dressed up.
    assert _indian_scale(4_200) == ""
    assert _indian_scale(None) == ""
    assert _indian_scale(float("nan")) == ""


def test_no_run_chunk_is_truncated_out_of_its_own_caveat(compared):
    """A chunk over the cap loses its END, and a rupee figure needs its caveat."""
    from app.assistant.context import MAX_CHUNK_CHARS

    for chunk in solver_run_chunks(compared):
        survives = chunk.text[:MAX_CHUNK_CHARS]
        if "INR per year" not in survives:
            continue
        assert "ENERGY CHARGE ONLY" in survives, chunk.id
        assert "not an electricity bill" in survives, chunk.id


def test_the_context_budget_reserves_room_for_the_attached_run(compared):
    """The root cause: retrieval reserved slots, assembly then ignored them."""
    from app.assistant import context as context_module

    question = "What's the estimated annual loss cost for this run?"
    scored = service.retrieve(question, run=compared)
    _block, used = context_module.assemble(scored)

    solver_used = [s for s in used if s.chunk.kind == "solver"]
    assert solver_used, "the run was retrieved but never made it into the prompt"
    assert len(solver_used) <= context_module.RESERVED_SOLVER_CHUNKS + 2
    # The reservation is a floor for the run, not a takeover of the context.
    assert any(s.chunk.kind != "solver" for s in used)


def test_a_run_chunk_is_not_dropped_by_the_index_score_floor(compared):
    """Run chunks are scored over ten chunks; the floor is tuned for 357."""
    from app.assistant import context as context_module

    scored = service.retrieve("What is the hybrid distance?", run=compared)
    _block, used = context_module.assemble(scored)

    assert any(s.chunk.kind == "solver" for s in used), [
        (s.chunk.id, s.score) for s in scored
    ]


@pytest.mark.parametrize("question", [
    "What is the boiling point of mercury on Venus?",
    "Who won the 2019 cricket world cup final?",
])
def test_an_attached_run_does_not_make_off_topic_answerable(
    client, spy_llm, compared, question,
):
    """Loosening the floor for the run must not open a door for anything else."""
    body = client.post(
        "/assistant/query", json={"question": question, "run": compared},
    ).json()

    assert body["grounded"] is False
    assert body["answer"] == UNAVAILABLE
    assert body["sources"] == []
    assert spy_llm == []


def test_the_qubit_count_cannot_be_multiplied_into_a_bigger_one(compared):
    """From a real failure: the model answered "9 x 26 = 234 qubits".

    The run prints qubits per subproblem and a subproblem count, and a small
    model read those two numbers as factors. Qubits are a circuit WIDTH and the
    subproblems run one after another, so there is nothing to add up - the
    context now says so where the two numbers appear.
    """
    detail = {chunk.id: chunk.text for chunk in solver_run_chunks(compared)}
    text = detail["run:hybrid-detail"]

    assert "QUBITS USED IN THIS RUN" in text
    assert "do not multiply this number by anything" in text
    assert str(compared["hybrid"]["detail"]["qubits_per_subproblem"]) in text


def test_the_prompt_routes_run_questions_to_the_run(client, spy_llm, compared):
    client.post(
        "/assistant/query",
        json={"question": "What's the hybrid modeled loss?", "run": compared},
    )
    system = spy_llm[-1]["system"]

    assert "WHEN THE QUESTION IS ABOUT THE RUN, ANSWER FROM THE RUN" in system
    assert "do not answer from the dataset as though it were the run" in system


def test_unit_restatement_is_permitted_only_for_the_run(client, spy_llm, compared):
    """The ban on calculation stands; restating a run figure's scale does not."""
    client.post(
        "/assistant/query",
        json={"question": "What's the estimated annual loss cost for this run?",
              "run": compared},
    )
    system = spy_llm[-1]["system"]

    # The absolute rule is still there, unweakened.
    assert "NEVER CALCULATE A FIGURE" in system
    assert "A calculated number is a fabricated number" in system
    # And the exception is scoped to the run, and to scale only.
    assert "ONE NARROW EXCEPTION, and only for the run" in system
    assert "never licenses applying a formula" in system
