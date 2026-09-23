"""Assembling retrieved chunks into the block the model is allowed to read.

Two jobs, and nothing else happens here:

1. Bound the context. A hard character budget means one very long documentation
   section cannot crowd out the dataset record that actually answers the
   question. Chunks are added best-first until the budget is spent.
2. Label every chunk with its provenance, in the text itself. The model is told
   to attribute what it says, and it can only do that if each piece of context
   arrives carrying its own source line.
"""

from __future__ import annotations

from typing import Iterable

#: Characters of retrieved context handed to the model.
#:
#: This number is a LATENCY setting as much as a quality one, and the measured
#: reason is worth recording. Generation runs on a local 3B model on CPU, which
#: processes prompt tokens at roughly 30-40/s, and Ollama does not reuse the
#: cached prefix between two different questions - so every question pays a full
#: prefill of the whole prompt before a single token comes back. Measured here:
#:
#:      3,701-token prompt  ->  91s prefill  +  9s generation
#:
#: Prefill was 91% of the wall time; retrieval was 0.05ms. Context size is
#: therefore the dominant term in how long an answer takes, and the budget is
#: set to what an answer actually needs rather than to what the window allows.
#: Raising it back to 14000 roughly triples the wait per question.
#:
#: (Two things that do NOT help, both measured: lowering the model's num_ctx is
#: slower, not faster, and it risks silent truncation; and streaming would not
#: help either, because the wait is prefill, before the first token exists.)
CONTEXT_BUDGET_CHARS = 6500

#: A chunk longer than this is truncated rather than dropped, so an over-long
#: document section still contributes its opening instead of crowding out the
#: dataset record that answers the question - and costing 30s to do it.
MAX_CHUNK_CHARS = 1400

#: Chunks of the caller's own run that are guaranteed a place in the budget.
#:
#: THIS IS A BUG FIX, and the bug is worth recording because the two halves of
#: it looked fine on their own.
#:
#: `CompositeRetriever` reserves slots for the attached run so that a run chunk -
#: necessarily longer than a CSV row, and penalised by BM25's length
#: normalisation for it - still reaches the answer when the question is about
#: the run. That reservation was then thrown away HERE: this function walked the
#: merged list in pure score order and spent the whole budget on the first few
#: chunks. For "what's the estimated annual loss cost for this run?" the run's
#: own energy figures were retrieved at rank 5, four documentation and code
#: chunks filled 6,500 characters ahead of them, and the model was handed a
#: tariff formula with no run attached to apply it to - so it answered, quite
#: correctly for what it could see, that it did not have enough information.
#:
#: Reserving budget, not just retrieval slots, is what makes the two stages
#: agree. A run chunk still has to pass the same relevance gate as everything
#: else, so an off-run question still retrieves none.
RESERVED_SOLVER_CHUNKS = 2

#: Below this BM25 score a chunk is noise - one incidental word in common.
#: Kept low: dropping a real match is worse than including a weak one, because
#: the model can ignore an irrelevant record but cannot invent a missing one.
MIN_SCORE = 0.6

#: Stated once per request, ahead of the retrieved records, whenever a dataset
#: record is among them.
#:
#: This text used to live inside all 38 transmission-line chunks - 645 repeated
#: characters against 469 characters of actual fact in each one. Retrieving four
#: records therefore spent most of its context budget restating the same caveat
#: four times, which on a local CPU model is seconds of prompt processing for
#: nothing. Hoisting it here keeps every word of the rule and its authority
#: while paying for it once, and the budget it frees goes to carrying MORE
#: dataset records - which is what actually makes the answer right.
DATASET_STANDING = (
    "HOW TO READ THE DATASET RECORDS BELOW. Distance_km, Voltage_kV, "
    "Capacity_MW, Loss_Percent and Energy_Loss_MW are SOURCE columns: they "
    "arrived with the dataset and are read, never recomputed. They are modeled "
    "values - the dataset carries no measurement provenance, no load factor and "
    "no operating schedule - so they are not metered readings, and the distance "
    "is not a survey this project performed. Loss_Cost_Per_Hour_INR and "
    "Loss_Cost_Per_Year_INR are DERIVED columns this project calculated from "
    "Energy_Loss_MW and the published tariff. Energy_Loss_MW is a property of "
    "the line, not of a trip across it: crossing a line twice does not double "
    "it.\n"
    "Each record names the two stations it joins. Match the question to a "
    "record by those station names. If more than one record could be meant, or "
    "none clearly is, say so - never answer from a record for a different "
    "line.\n"
)

KIND_LABELS = {
    "dataset": "PROJECT DATASET RECORD",
    "doc": "PROJECT DOCUMENTATION / APPROVED REFERENCE",
    "code": "PROJECT SOURCE CODE (this repository's own implementation)",
    "solver": "ACTUAL SOLVER RUN OUTPUT",
}


def _render(index: int, scored) -> str:
    chunk = scored.chunk
    body = chunk.text
    if len(body) > MAX_CHUNK_CHARS:
        body = body[:MAX_CHUNK_CHARS].rstrip() + "\n[... this section continues ...]"

    label = KIND_LABELS.get(chunk.kind, chunk.kind.upper())
    return (
        f"--- SOURCE {index} | {label} ---\n"
        f"Title: {chunk.title}\n"
        f"Location: {chunk.locator}\n\n"
        f"{body}\n"
    )


def assemble(scored_chunks: Iterable, budget: int = CONTEXT_BUDGET_CHARS) -> tuple:
    """Retrieved chunks -> `(context_block, used)`.

    `used` is the list of `ScoredChunk` that actually made it into the block, in
    the order they appear. The endpoint reports exactly those as its sources, so
    a citation always corresponds to something the model could read.
    """
    used: list = []
    rendered: list = []
    scored_chunks = list(scored_chunks)

    # The caller's own run goes in first, up to its reservation. Everything
    # else follows in score order, including any further run chunks - they
    # simply lose their guarantee, not their place.
    # The score floor is not applied to the caller's own run, and that is not a
    # concession - it is a correction. Run chunks are scored by a separate
    # retriever over a ten-chunk corpus, so BM25's IDF makes exactly the terms
    # that matter worthless: "hybrid" and "distance" appear in nearly every
    # chunk of a run, which drives their weight to zero and the chunk's score
    # under a floor calibrated on a 357-chunk index. "What is the hybrid
    # distance?" scored 0.3 and was discarded. Scores from two different corpora
    # were never comparable; the term-coverage gate in `retrieval.py` is what
    # keeps an unrelated question from pulling the run in, and it still applies.
    eligible = [
        s for s in scored_chunks
        if s.score >= MIN_SCORE or (s.chunk.kind == "solver" and s.score > 0)
    ]
    reserved = [s for s in eligible if s.chunk.kind == "solver"][:RESERVED_SOLVER_CHUNKS]
    reserved_ids = {scored.chunk.id for scored in reserved}
    scored_chunks = reserved + [
        scored for scored in eligible if scored.chunk.id not in reserved_ids
    ]

    # The dataset caveat is charged against the budget up front when it applies,
    # so the budget keeps meaning what it says: total characters the model reads.
    preamble = (
        DATASET_STANDING
        if any(s.chunk.kind == "dataset" and s.score >= MIN_SCORE
               for s in scored_chunks)
        else ""
    )
    spent = len(preamble)

    # The floor was applied once, building `eligible` above - re-applying it
    # here is what silently undid the run exemption the first time.
    for scored in scored_chunks:
        piece = _render(len(used) + 1, scored)
        if spent + len(piece) > budget and used:
            break
        rendered.append(piece)
        used.append(scored)
        spent += len(piece)

    # No chunk cleared the score floor: return nothing at all, never a preamble
    # with no records under it, which would read as context that is not there.
    if not used:
        return "", []
    return preamble + "\n".join(rendered), used
