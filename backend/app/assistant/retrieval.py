"""Scoring chunks against a question.

WHY THIS IS LEXICAL AND NOT A VECTOR STORE
------------------------------------------
The brief asked for pgvector if it were practical with the existing setup. It is
not, and the reason is worth writing down rather than discovering later:

  * The FastAPI backend has no database connectivity at all. It reads the CSV
    through `phase1.data_loader` and holds nothing in Postgres; there is no
    driver in `backend/requirements.txt` and no connection in `app/core`. The
    Supabase schema in `supabase/` is a seeded mirror of the same CSV, used by
    nothing on the server path.
  * pgvector stores embeddings, and embeddings have to come from somewhere.
    Generation here is a LOCAL Ollama model precisely so that nothing leaves the
    machine and nothing is billed; wiring a cloud embedding vendor back in would
    undo both at once. Reaching pgvector would therefore mean adding a Postgres
    driver, a remote migration, and either that vendor or a second local model
    kept resident - to serve a corpus of a few hundred short chunks.

So retrieval is BM25 over the same chunks, computed in process. It is
deterministic, needs no key, runs offline, and is exact on the thing this corpus
is actually asked about - station names, line pairs, column names. The contract
below is what keeps the door open: `Retriever` is the whole interface the rest of
the package depends on, so a `PgVectorRetriever` can replace `Bm25Retriever`
without touching `service.py`, the endpoint or the frontend.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional, Protocol

from app.assistant.documents import Chunk, ScoredChunk

# BM25 parameters. k1 controls term-frequency saturation, b the length
# normalisation. These are the standard defaults and there is no reason to tune
# them for a corpus this size.
K1 = 1.5
B = 0.75

#: Words carrying no discriminating power in questions about this project.
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have
how i if in into is it its me my of on or our over should so such than that the
their them then there these they this those to was we were what when where
which who why will with would you your about tell explain me please give show
""".split())

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

#: Suffixes stripped so a question's word form matches the corpus's.
#:
#: BM25 compares literal terms, and without this the mismatches are silent and
#: total: "Why are 625 qubits required?" does not match "qubit", "rupees" does
#: not match "rupee", "are you optimizing energy loss?" does not match
#: "optimizes", "sweeps" does not match "sweep". The corpus and the question are
#: written by different people on different days, so they will not agree on
#: number and tense.
#:
#: Deliberately crude - longest suffix first, and only when a real word is left
#: behind (MIN_STEM). A proper stemmer (Porter, Snowball) is a dependency and an
#: over-solution for a few hundred chunks; the conflations that matter here are
#: plural and tense. Applied to the corpus and the question by the same
#: function, so the two can only ever agree.
_SUFFIXES = ("ings", "ing", "ies", "es", "ed", "s")
MIN_STEM = 4


def stem(token: str) -> str:
    """Strip a plural or tense suffix when a real word remains underneath."""
    if len(token) <= MIN_STEM or not token.isalpha():
        return token

    base = token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM:
            # "ies" -> "y" keeps "policies"/"policy" together; the rest are
            # simple truncations.
            stripped = token[: -len(suffix)]
            base = stripped + "y" if suffix == "ies" else stripped
            break

    # A trailing "e" goes too, so the three forms of a verb land on one term:
    # optimize / optimizes / optimizing all become "optimiz". Without it the
    # bare form is the odd one out, which is the form documentation uses.
    if base.endswith("e") and len(base) > MIN_STEM:
        base = base[:-1]
    return base


def tokenize(text: str) -> list:
    """Lowercase word tokens, stopwords dropped, plural/tense suffixes stripped.

    Underscores are split so `Energy_Loss_MW` in a question matches
    `Energy_Loss_MW` in a chunk term by term as well as whole.
    """
    lowered = text.lower().replace("_", " ").replace("->", " ")
    return [
        stem(token) for token in _TOKEN.findall(lowered)
        if token not in STOPWORDS
    ]


#: A chunk qualifies only if it matches at least this fraction of the question's
#: distinctive terms (stopwords already removed).
#:
#: This gate, not the BM25 score, is what makes an off-topic question return
#: nothing. A raw score threshold cannot do it: BM25 scores are unnormalised, so
#: "what is the boiling point of mercury" can out-score a real dataset question
#: purely because one incidental rare word happens to appear somewhere in the
#: corpus. Term coverage asks the question that actually matters - is this chunk
#: about what was asked, or does it merely share a word with it - and an empty
#: result is the correct, honest outcome when nothing is.
MIN_TERM_COVERAGE = 0.4


class Retriever(Protocol):
    """The only retrieval contract the rest of the package knows about."""

    def search(self, question: str, top_k: int) -> list:
        """Return up to `top_k` `ScoredChunk`, best first. May return [].
        """
        ...


class Bm25Retriever:
    """BM25 over an in-memory chunk collection.

    Built once per index load and reused. Scoring a question against a few
    hundred chunks is microseconds, so there is no caching layer here.
    """

    def __init__(self, chunks: Iterable[Chunk]):
        self.chunks = list(chunks)
        self._tokens = [tokenize(f"{c.title} {c.locator} {c.text}") for c in self.chunks]
        self._lengths = [len(t) for t in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        # term -> {chunk index: frequency}
        self._postings: dict = {}
        for index, tokens in enumerate(self._tokens):
            counts: dict = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                self._postings.setdefault(token, {})[index] = count

    def __len__(self) -> int:
        return len(self.chunks)

    def _idf(self, term: str) -> float:
        total = len(self.chunks)
        seen = len(self._postings.get(term, ()))
        if seen == 0:
            return 0.0
        # BM25's probabilistic idf, floored at a small positive value so a term
        # in more than half the corpus does not score negatively.
        return max(math.log(1.0 + (total - seen + 0.5) / (seen + 0.5)), 1e-6)

    def search(self, question: str, top_k: int) -> list:
        terms = tokenize(question)
        if not terms or not self.chunks:
            return []

        distinct_terms = set(terms)
        needed = max(1, math.ceil(MIN_TERM_COVERAGE * len(distinct_terms)))

        scores: dict = {}
        matched: dict = {}
        for term in distinct_terms:
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self._idf(term)
            for index, frequency in postings.items():
                length = self._lengths[index] or 1
                norm = 1 - B + B * (length / (self._avg_length or 1))
                contribution = idf * (frequency * (K1 + 1)) / (frequency + K1 * norm)
                scores[index] = scores.get(index, 0.0) + contribution
                matched[index] = matched.get(index, 0) + 1

        # The coverage gate is applied BEFORE the top-k cut. Filtering after it
        # would silently shrink the result: a qualifying chunk ranked just
        # outside the cut would be dropped in favour of nothing.
        qualified = [
            (index, score) for index, score in scores.items()
            if score > 0 and matched.get(index, 0) >= needed
        ]
        qualified.sort(key=lambda pair: (-pair[1], pair[0]))

        return [
            ScoredChunk(chunk=self.chunks[index], score=round(score, 4))
            for index, score in qualified[:top_k]
        ]


class CompositeRetriever:
    """The project index plus the caller's own run, merged into one result.

    The run gets reserved slots rather than competing on score, and the reason
    is mechanical: BM25 normalises by document length, and a run chunk - a whole
    26-station tour, or a full comparison - is several times longer than a
    single CSV row. On a question that is plainly about the run ("what distance
    did the hybrid route come out at?") the run's own output would lose to a
    documentation paragraph that merely uses the same words more densely. That
    is exactly backwards.

    Reserving slots is not a thumb on the scale for relevance: a run chunk still
    has to pass the same coverage gate as everything else, so a question the run
    has nothing to do with still retrieves no run context. It only guarantees
    that when the run IS relevant, the model reads the real output instead of
    prose about what such output looks like.
    """

    def __init__(self, primary: Retriever, run_retriever: Optional[Retriever] = None,
                 reserved: int = 3):
        self.primary = primary
        self.run_retriever = run_retriever
        self.reserved = reserved

    def search(self, question: str, top_k: int) -> list:
        if self.run_retriever is None:
            return self.primary.search(question, top_k)

        slots = min(self.reserved, max(1, top_k // 2))
        from_run = self.run_retriever.search(question, slots)
        from_index = self.primary.search(question, top_k)

        merged: dict = {}
        for scored in [*from_run, *from_index]:
            current = merged.get(scored.chunk.id)
            if current is None or scored.score > current.score:
                merged[scored.chunk.id] = scored

        run_hits = [s for s in merged.values() if s.chunk.kind == "solver"]
        other = [s for s in merged.values() if s.chunk.kind != "solver"]
        run_hits.sort(key=lambda s: -s.score)
        other.sort(key=lambda s: -s.score)

        kept = run_hits[:slots] + other[: max(0, top_k - len(run_hits[:slots]))]
        return sorted(kept, key=lambda s: -s.score)[:top_k]
