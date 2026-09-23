"""Splitting long project prose into retrievable pieces.

Two rules shape this:

1. Split on headings first. The project's documentation is Markdown, and a
   heading is already the author's own statement of where one topic ends and
   the next begins - a better boundary than any character count.
2. Carry the heading trail into every piece. A chunk is retrieved and shown on
   its own, so "Rs. 6.60/kWh" has to arrive with the section that says what it
   is. Without the trail the model would have to guess, which is the one thing
   it must not do.

Long sections are then split on paragraph boundaries, with a small overlap so a
fact stated across a paragraph break is not lost at the seam.
"""

from __future__ import annotations

import re

#: Target size in characters. Roughly 250-350 tokens - large enough to hold a
#: complete definition, small enough that eight of them stay readable.
TARGET_CHARS = 1400
#: Sections shorter than this are merged into the next one rather than becoming
#: a chunk that says only "## 3. Monetary loss".
MIN_CHARS = 200
#: Characters repeated from the previous piece when a section has to be split.
OVERLAP_CHARS = 160

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _heading_trail(stack: list) -> str:
    return " > ".join(title for _, title in stack)


def split_markdown(text: str) -> list:
    """Split Markdown into `(heading_trail, body)` pairs.

    Fenced code blocks are never split: a formula shown as code is a single
    fact and is useless in halves.
    """
    sections: list = []
    stack: list = []
    body: list = []
    in_fence = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append((_heading_trail(stack), content))
        body.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            body.append(line)
            continue

        match = None if in_fence else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue

        body.append(line)

    flush()
    return sections


def _split_long(body: str) -> list:
    """Break one over-long section on paragraph boundaries, with overlap."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces: list = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= TARGET_CHARS or not current:
            current = candidate
            continue
        pieces.append(current)
        tail = current[-OVERLAP_CHARS:]
        current = f"{tail}\n\n{paragraph}" if OVERLAP_CHARS else paragraph

    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(text: str) -> list:
    """Markdown -> a list of `(heading_trail, chunk_text)` ready to index.

    Every returned chunk text is prefixed with its heading trail, so it stands
    alone once retrieved.
    """
    results: list = []
    pending_trail = ""
    pending_body = ""

    for trail, body in split_markdown(text):
        if pending_body:
            body = f"{pending_body}\n\n{body}"
            trail = pending_trail or trail
            pending_trail, pending_body = "", ""

        if len(body) < MIN_CHARS:
            pending_trail, pending_body = trail, body
            continue

        for piece in _split_long(body):
            header = f"[{trail}]\n" if trail else ""
            results.append((trail, f"{header}{piece}".strip()))

    if pending_body:
        header = f"[{pending_trail}]\n" if pending_trail else ""
        results.append((pending_trail, f"{header}{pending_body}".strip()))

    return results
