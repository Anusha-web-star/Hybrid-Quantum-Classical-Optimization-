"""The GRIDOPT project assistant: grounded retrieval over the project's own data.

The rule this package exists to enforce is that the assistant never invents a
Karnataka grid fact, a route, a solver result, a cost or a piece of methodology.
Everything it says has to be traceable to something already in this repository:
the transmission-line CSV, an actual solver run the caller supplies, the
project's own written documentation, or the project's own source code.

Layout, one responsibility per module:

    documents.py   the Chunk record and its source descriptor
    chunking.py    splitting long prose into retrievable pieces
    sources.py     project data and curated docs -> chunks (ingestion)
    primer.py      the curated project knowledge, one entry per explainable thing
    code.py        an allowlist of this repository's source files -> chunks
    runcontext.py  an actual solver-run payload -> chunks
    index.py       building, saving and loading the knowledge base
    retrieval.py   scoring chunks against a question (the Retriever contract)
    context.py     assembling retrieved chunks into a bounded prompt context
    prompts.py     the grounding system instruction
    llm.py         the local model call, via Ollama on loopback
    service.py     the pipeline the endpoint calls
    reindex.py     the re-indexing entry point
"""
