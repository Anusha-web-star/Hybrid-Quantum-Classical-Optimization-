"""The source-code knowledge layer: this repository's own implementation.

WHY THIS EXISTS
---------------
Prose says what the project intends. The code says what it does. A question like
"why did the hybrid route come out shorter than the NN one?" is answered by
`phase2/hybrid.py` - the acceptance test on line "if ordering is not None and
length < current - 1e-9" is the whole answer - and no amount of README is a
substitute for it.

WHAT IS INDEXED, AND WHAT CANNOT BE
-----------------------------------
An EXPLICIT ALLOWLIST of project files, listed in `CODE_SOURCES` below. Nothing
is discovered by walking the tree, so a file can only be indexed by being named
here on purpose. `.env`, credentials, keys, the virtualenv, build output and
generated seed data are not on the list and cannot be reached by this module.

As a second line of defence, every emitted text passes through `redact()`, which
blanks anything shaped like an assigned secret. The allowlist is the control;
the redactor is the seatbelt.

HOW A FILE BECOMES CHUNKS
-------------------------
Python is parsed with `ast` (standard library - no new dependency) and split at
its own boundaries: one chunk for the module, one per top-level class, one per
top-level function. That is the unit a technical question is actually about, and
it keeps a retrieved chunk self-contained: a signature, its docstring and the
body that implements it.

Everything else on the list (JavaScript, JSX, SQL) is indexed as one chunk per
file, built from its header comment and its exported/declared names. Those files
are documented at the top rather than per function, so the header IS the unit.

Bodies are bounded (`MAX_BODY_CHARS`). A retrieved chunk that does not fit the
prompt budget is truncated by `context.py` anyway, so a 400-line function is
carried as its opening rather than crowding out the three other chunks that
together answer the question.

DETERMINISM
-----------
The list is a tuple, files are read in that order, and `ast` walks a module top
to bottom. Re-indexing the same working tree therefore produces the same chunks
with the same ids in the same order - which is what makes the index a derived
artefact that can be deleted and rebuilt without consequence.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from app.assistant.documents import Chunk

#: Repository root: backend/app/assistant/code.py -> parents[3].
PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Characters of implementation carried per unit.
#:
#: Kept deliberately below `context.MAX_CHUNK_CHARS`. The prompt has a fixed
#: character budget, so chunk size and chunk COUNT trade off directly: at 1100
#: characters of body a question that retrieved code filled the budget with
#: three chunks and dropped the written explanation that answered it. The
#: signature, the docstring and the opening of a function carry the part of the
#: answer a reader needs; the rest is a file away, and the locator says where.
MAX_BODY_CHARS = 700
#: Characters of a module or file header carried with a unit.
MAX_HEADER_CHARS = 500

#: The allowlist: (repo-relative path, what this file is, in one line).
#:
#: Ordered by the pipeline it belongs to, because that is also the order a
#: reader would want them. Adding a file here is the ONLY way to index it.
CODE_SOURCES: tuple = (
    # --- Phase 1: dataset, graph, classical solver ------------------------
    ("phase1/data_loader.py",
     "Phase 1 - reads the transmission-line CSV into stations and connections"),
    ("phase1/network.py",
     "Phase 1 - the transmission network as a graph, with Dijkstra shortest-path "
     "closure over Distance_km"),
    ("phase1/nn_tsp.py",
     "Phase 1 - the classical Nearest Neighbour TSP solver"),

    # --- Phase 2: QUBO, Ising, QAOA, hybrid loop, backends ----------------
    ("phase2/qubo.py",
     "Phase 2 - TSP and path-TSP written as a QUBO with position encoding"),
    ("phase2/ising.py",
     "Phase 2 - QUBO to Ising Hamiltonian (SparsePauliOp of Z and ZZ terms)"),
    ("phase2/qaoa.py",
     "Phase 2 - the QAOA optimization engine: ansatz, CVaR objective, COBYLA, "
     "decoding and scoring of sampled bitstrings"),
    ("phase2/hybrid.py",
     "Phase 2 - the hybrid quantum-classical loop: sliding-window QAOA "
     "reoptimization of a full 26-station tour"),
    ("phase2/instance.py",
     "Phase 2 - the TSP instance handed to the quantum pipeline"),
    ("phase2/backends.py",
     "Phase 2 - where circuits run: the local Aer simulator, or IBM Quantum "
     "hardware when explicitly opted in"),
    ("phase2/comparison.py",
     "Phase 2 - comparing the classical and hybrid routes on the same problem"),

    # --- Energy and money evaluation --------------------------------------
    ("energy_cost/route_loss.py",
     "Maps a solved route onto the physical transmission lines it uses and "
     "sums the modeled energy loss over the DISTINCT lines"),
    ("energy_cost/tariff.py",
     "The KERC tariff record and the hourly/annual cost functions"),
    ("energy_cost/recompute.py",
     "Recomputes the CSV's derived rupee columns from Energy_Loss_MW"),

    # --- The FastAPI backend ----------------------------------------------
    ("backend/app/main.py",
     "FastAPI application factory: routers, CORS and the auth dependency"),
    ("backend/app/api/routes/solve.py",
     "API - the solver endpoints: /solve/classical, /solve/hybrid, /solve/compare"),
    ("backend/app/api/routes/network.py",
     "API - the network endpoint"),
    ("backend/app/api/routes/stations.py",
     "API - the station list and start-station resolution"),
    ("backend/app/api/routes/graphs.py",
     "API - the generated route figures"),
    ("backend/app/api/routes/assistant.py",
     "API - the assistant endpoints: POST /assistant/query, GET /assistant/status"),
    ("backend/app/services/solver.py",
     "API service layer - runs the Phase 1 and Phase 2 solvers for a request"),
    ("backend/app/services/serialize.py",
     "API service layer - turns solver objects into the JSON the API returns"),
    ("backend/app/core/auth.py",
     "API - the authentication dependency"),
    ("backend/app/core/config.py",
     "API - settings and their defaults, read from the environment"),

    # --- The assistant itself ---------------------------------------------
    ("backend/app/assistant/retrieval.py",
     "Assistant - BM25 lexical retrieval and why it is not a vector store"),
    ("backend/app/assistant/service.py",
     "Assistant - the RAG pipeline: retrieve, assemble context, generate, cite"),
    ("backend/app/assistant/llm.py",
     "Assistant - the local Ollama call, restricted to loopback"),
    # NOT listed, deliberately: primer.py and code.py, the two ingestion modules
    # of this knowledge base. Their source is a catalogue of every topic and
    # every indexed filename, so as chunks they match almost any question about
    # the project and crowd out the chunks that actually answer it. What they
    # produce is indexed; what produces it is not.
    ("backend/app/assistant/runcontext.py",
     "Assistant - the attached optimization run, turned into retrievable context"),

    # --- The React frontend ------------------------------------------------
    ("frontend/src/App.jsx",
     "Frontend - the application shell: intro, access screen, console"),
    ("frontend/src/hooks/useOptimization.js",
     "Frontend - what the Run Optimization button actually does"),
    ("frontend/src/hooks/useNetwork.js",
     "Frontend - loading the network for the map"),
    ("frontend/src/hooks/useAssistant.js",
     "Frontend - the assistant panel's question/answer state"),
    ("frontend/src/hooks/useRoutePlayback.js",
     "Frontend - route animation and playback"),
    ("frontend/src/api/client.js",
     "Frontend - the HTTP client for the FastAPI backend"),
    ("frontend/src/api/gridopt.js",
     "Frontend - one function per API endpoint"),
    ("frontend/src/lib/supabase.js",
     "Frontend - the Supabase browser client used for sign-in, built from the "
     "public key only"),
    ("frontend/src/hooks/useAuth.js",
     "Frontend - the Supabase Auth session: sign-up, sign-in, sign-out and "
     "onAuthStateChange"),
    ("frontend/src/components/network/NetworkCanvas.jsx",
     "Frontend - the network and route visualization"),
    ("frontend/src/components/results/ResultsColumn.jsx",
     "Frontend - the NN vs hybrid results panel"),
    ("frontend/src/components/energy/EnergyTable.jsx",
     "Frontend - the energy-loss and cost table"),
    ("frontend/src/components/assistant/AssistantPanel.jsx",
     "Frontend - the assistant panel and its source chips"),

    # --- The database ------------------------------------------------------
    ("supabase/schema.sql",
     "Database - the Supabase PostgreSQL schema, its view and its RLS policies"),
)

#: Anything that looks like an assigned credential is blanked before indexing.
#: This never fires on the allowlist above - it is here so that adding a file to
#: the list can never turn into publishing a secret through the assistant.
_SECRET = re.compile(
    r"""(?ix)
    \b(
      token | secret | password | passwd | passphrase | credential |
      api[_-]?key | access[_-]?key | service[_-]?role[_-]?key |
      publishable[_-]?key | anon[_-]?key | bearer
    )
    (\s*["']?\s*[:=]\s*)
    (["'][^"'\n]{6,}["'])
    """
)

#: Environment-variable NAMES are useful ("IBM_QUANTUM_TOKEN is read from the
#: environment"); a value assigned to one is not. This catches `FOO_TOKEN=abc`
#: in a docstring or a shell example.
_ENV_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD))\s*=\s*(\S{6,})"
)


def redact(text: str) -> str:
    """Blank anything shaped like an assigned secret. Names are kept, values go."""
    text = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}\"<redacted>\"", text)
    return _ENV_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=<redacted>", text)


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[... continues in the file ...]"


def _signature(node) -> str:
    """The def/class line as written, without the body."""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else (
        "def " if isinstance(node, ast.FunctionDef) else "class "
    )
    try:
        args = ast.unparse(node.args) if hasattr(node, "args") else ""
    except Exception:  # pragma: no cover - unparse is total on parsed source
        args = ""
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases}):" if bases else f"class {node.name}:"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix}{node.name}({args}){returns}:"


def _unit_chunk(relative: str, label: str, header: str, node, lines: list) -> Chunk:
    """One top-level function or class, as a retrievable chunk."""
    kind_word = "class" if isinstance(node, ast.ClassDef) else "function"
    body = "\n".join(lines[node.lineno - 1: node.end_lineno])
    docstring = ast.get_docstring(node) or ""

    methods = [
        f"  - {child.name}(): {(ast.get_docstring(child) or '').splitlines()[0] if ast.get_docstring(child) else 'no docstring'}"
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    ] if isinstance(node, ast.ClassDef) else []

    text = "\n".join([
        f"PROJECT SOURCE CODE - {relative}, {kind_word} {node.name}().",
        f"What this file is: {label}",
        f"Defined at {relative} lines {node.lineno}-{node.end_lineno}.",
        "",
        f"Signature: {_signature(node)}",
        *([f"Documented as: {_clip(docstring, 600)}"] if docstring else []),
        *(["Methods:", *methods] if methods else []),
        *([f"", f"Context from the top of {relative}: {header}"] if header else []),
        "",
        "Implementation as written in the repository:",
        _clip(body, MAX_BODY_CHARS),
    ])

    return Chunk(
        id=f"code:{_slug(relative)}:{node.name}",
        kind="code",
        title=f"{relative} - {kind_word} {node.name}()",
        locator=f"{relative} lines {node.lineno}-{node.end_lineno}",
        text=redact(text),
        metadata={"file": relative, "symbol": node.name, "unit": kind_word},
    )


def _module_chunk(relative: str, label: str, header: str, tree, lines: list) -> Chunk:
    """The file itself: what it is for, and what it defines."""
    defined = [
        ("class " if isinstance(node, ast.ClassDef) else "def ") + node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    constants = [
        target.id
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.isupper()
    ]

    text = "\n".join([
        f"PROJECT SOURCE CODE - the module {relative}.",
        f"What this file is: {label}",
        f"Length: {len(lines)} lines.",
        "",
        *([f"What the module says about itself:\n{header}"] if header else []),
        "",
        f"Defined in this module: {', '.join(defined) or 'no top-level definitions'}",
        *([f"Module-level constants: {', '.join(constants)}"] if constants else []),
    ])

    return Chunk(
        id=f"code:{_slug(relative)}",
        kind="code",
        title=f"{relative} - module overview",
        locator=relative,
        text=redact(text),
        metadata={"file": relative, "unit": "module"},
    )


def _python_chunks(relative: str, label: str, source: str) -> list:
    """Module chunk plus one chunk per top-level class and function."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A file that does not parse is skipped rather than indexed as prose:
        # half-parsed code is worse than none.
        return []

    lines = source.splitlines()
    header = _clip(ast.get_docstring(tree) or "", MAX_HEADER_CHARS)
    chunks = [_module_chunk(relative, label, header, tree, lines)]

    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(_unit_chunk(relative, label, header, node, lines))

    return chunks


_JS_HEADER = re.compile(r"^\s*/\*\*(.*?)\*/", re.DOTALL)
_JS_EXPORT = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class)\s+(\w+)",
    re.MULTILINE,
)
_JS_CONST = re.compile(r"^const\s+([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


def _javascript_chunks(relative: str, label: str, source: str) -> list:
    """One chunk per frontend file: its header docblock and what it exports.

    The frontend files document themselves at the top - that block is the
    author's own statement of what the file does - and the bodies are React
    rendering, which answers few questions a viva asks. So the header is the
    unit here, not each function.
    """
    match = _JS_HEADER.search(source)
    header = ""
    if match:
        header = "\n".join(
            line.strip().lstrip("*").strip()
            for line in match.group(1).splitlines()
        ).strip()

    exports = _JS_EXPORT.findall(source)
    constants = _JS_CONST.findall(source)

    text = "\n".join([
        f"PROJECT SOURCE CODE - the frontend file {relative}.",
        f"What this file is: {label}",
        f"Length: {len(source.splitlines())} lines.",
        "",
        *([f"What the file says about itself:\n{_clip(header, 1400)}"] if header
          else ["This file carries no header comment."]),
        "",
        f"Exported from this file: {', '.join(exports) or 'nothing exported'}",
        *([f"Module-level constants: {', '.join(constants)}"] if constants else []),
    ])

    return [Chunk(
        id=f"code:{_slug(relative)}",
        kind="code",
        title=f"{relative} - frontend module",
        locator=relative,
        text=redact(text),
        metadata={"file": relative, "unit": "frontend-module"},
    )]


def _sql_chunks(relative: str, label: str, source: str) -> list:
    """One chunk per SQL file: its header comments and the objects it creates."""
    header_lines = []
    for line in source.splitlines():
        if line.startswith("--"):
            header_lines.append(line.lstrip("- ").rstrip())
        elif line.strip():
            break

    created = re.findall(
        r"(?im)^\s*create\s+(?:or\s+replace\s+)?(table|view|policy|index|function)"
        r"\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)",
        source,
    )
    objects = [f"  - {kind} {name}" for kind, name in created]

    text = "\n".join([
        f"PROJECT SOURCE CODE - the SQL file {relative}.",
        f"What this file is: {label}",
        "",
        f"What the file says about itself:\n{_clip(chr(10).join(header_lines), 1200)}",
        "",
        "Database objects created by this file:",
        *(objects or ["  - none detected"]),
    ])

    return [Chunk(
        id=f"code:{_slug(relative)}",
        kind="code",
        title=f"{relative} - database schema",
        locator=relative,
        text=redact(text),
        metadata={"file": relative, "unit": "sql"},
    )]


def code_chunks(root: Optional[Path] = None) -> tuple:
    """Every allowlisted source file, as chunks.

    Returns `(chunks, missing)`. A file that is not on disk is reported and
    skipped; nothing is substituted for it.
    """
    base = root or PROJECT_ROOT
    chunks: list = []
    missing: list = []

    for relative, label in CODE_SOURCES:
        path = base / relative
        if not path.is_file():
            missing.append(relative)
            continue

        source = path.read_text(encoding="utf-8", errors="replace")
        suffix = path.suffix.lower()

        if suffix == ".py":
            chunks.extend(_python_chunks(relative, label, source))
        elif suffix in (".js", ".jsx"):
            chunks.extend(_javascript_chunks(relative, label, source))
        elif suffix == ".sql":
            chunks.extend(_sql_chunks(relative, label, source))

    return chunks, missing
