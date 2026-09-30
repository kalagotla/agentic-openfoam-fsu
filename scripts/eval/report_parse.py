"""Full-fidelity parser for a case's ``REPORT.md``.

``REPORT.md`` is the artefact this repo produces: an append-only narration
of every decision taken while authoring and running a case. The evaluation
harness scores that artefact, so it needs to read *all* of it — not just
the decision entries.

Two partial parsers already exist in the servers: the OpenFOAM server's
``_parse_decision_entries`` (feeds the decisions index) and the
consultant's ``_parse_report_entries`` (feeds annotation drafting). Both
keep only entries carrying a consultant field and drop info entries,
tables, retry links, and the verdict banner. Scoring needs every one of
those, so this module parses the whole grammar:

    ## [HH:MM:SS] phase / status — title  **[PENDING REVIEW]**
    _retry of: 'prior entry title'_

    - **Decision:** one line
    <details><summary>why · alternatives · when it breaks</summary>

    - **Why:** rationale _(cites: a, b)_
    - **Alternatives:** ...
    - **When it breaks:** ...

    </details>

    ### Table title

    | col | col |
    | --- | --- |
    | val | val |

    free-form details prose

plus the ``finalize_report`` verdict banner and decisions index, which are
bracketed by HTML comment markers at the top and bottom of the file.

The parser is deliberately tolerant: a malformed or truncated report is
evidence about the run, not a reason to raise. Anything unparseable is
kept in ``Entry.details`` so nothing is silently discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Grammar — mirrors what openfoam_mcp.tools.record_step / finalize_report emit
# ---------------------------------------------------------------------------

ENTRY_HEADER_RE = re.compile(
    r"^##\s+\[(?P<ts>\d{2}:\d{2}:\d{2})\]"
    r"\s+(?P<phase>[^/]+?)"
    r"\s+/\s+(?P<status>[^—]+?)"
    r"\s+—\s+(?P<title>.+?)"
    r"(?P<pending>\s+\*\*\[PENDING REVIEW\]\*\*)?$"
)

CONSULTANT_FIELD_RE = re.compile(
    r"^-\s+\*\*(Decision|Why|Alternatives|When it breaks):\*\*\s*(.*)$"
)
INLINE_CITES_RE = re.compile(r"\s*_\(cites:\s*(.*?)\)_\s*$")
RETRY_OF_RE = re.compile(r"^_retry of:\s*(?P<title>.+?)_\s*$")
TABLE_TITLE_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|(?P<cells>.*)\|\s*$")
TABLE_RULE_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

SUMMARY_BEGIN = "<!-- BEGIN SUMMARY - auto-generated, do not edit -->"
SUMMARY_END = "<!-- END SUMMARY -->"
DECISIONS_BEGIN = "<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->"
DECISIONS_END = "<!-- END DECISIONS TABLE -->"

VERDICT_RE = re.compile(r"^\*\*VERDICT:\s*(?P<verdict>[A-Z]+)\*\*\s*—\s*(?P<outcome>.*)$")
COUNTS_RE = re.compile(
    r"(?P<steps>\d+)\s+steps?\s+·\s+(?P<decisions>\d+)\s+decisions?\s+·\s+"
    r"(?P<retries>\d+)\s+retr(?:y|ies)\s+·\s+(?P<gaps>\d+)\s+gaps?"
)

# The sentinels record_step renders when a consultant field is left empty.
# They are *not* content — an entry carrying one has a gap, not a rationale.
GAP_WHY = "_uncited choice — no annotation, reference, or paper cited._"
GAP_ALTS = "_no alternatives surfaced._"
GAP_BREAKS = "_failure modes not characterized._"
GAP_SENTINELS = frozenset({GAP_WHY, GAP_ALTS, GAP_BREAKS})

FIELD_NAME_TO_KEY = {
    "Decision": "decision",
    "Why": "why",
    "Alternatives": "alternatives",
    "When it breaks": "when_it_breaks",
}

VALID_STATUSES = frozenset(
    {"ok", "warning", "error", "fixed", "info", "pending_review"}
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    """One ``record_step`` entry, with every field it can carry."""

    timestamp: str
    phase: str
    status: str
    title: str
    line_no: int
    pending_review: bool = False
    retry_of: str | None = None
    decision: str = ""
    why: str = ""
    alternatives: str = ""
    when_it_breaks: str = ""
    citations: list[str] = field(default_factory=list)
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    details: str = ""

    @property
    def is_decision(self) -> bool:
        """True when the entry records a *choice* rather than pure narration.

        Mirrors ``record_step``'s own rule: any consultant field filled, or
        a pending-review status (which is always a proposed decision).
        """
        return bool(
            self.decision
            or self.why
            or self.alternatives
            or self.when_it_breaks
            or self.citations
            or self.status == "pending_review"
        )

    @property
    def gaps(self) -> list[str]:
        """Consultant fields left empty on a decision entry.

        Citations satisfy the ``why`` gap even when the prose is empty —
        a bare citation is still grounding.
        """
        if not self.is_decision:
            return []
        out: list[str] = []
        if not self.why and not self.citations:
            out.append("why")
        if not self.alternatives:
            out.append("alternatives")
        if not self.when_it_breaks:
            out.append("when_it_breaks")
        return out


@dataclass
class Banner:
    """The ``finalize_report`` verdict banner."""

    verdict: str
    outcome: str
    steps: int
    decisions: int
    retries: int
    gaps: int


@dataclass
class Report:
    """A parsed ``REPORT.md``."""

    path: Path | None
    entries: list[Entry]
    banner: Banner | None = None
    decisions_index: list[dict[str, str]] = field(default_factory=list)
    finalized: bool = False

    @property
    def decisions(self) -> list[Entry]:
        return [e for e in self.entries if e.is_decision]

    @property
    def retries(self) -> list[Entry]:
        return [e for e in self.entries if e.retry_of]

    def by_phase(self, phase: str) -> list[Entry]:
        return [e for e in self.entries if e.phase == phase]

    def last_of_phase(self, phase: str) -> Entry | None:
        matches = [e for e in self.entries if phase in e.phase.lower()]
        return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _strip_quotes(s: str) -> str:
    """Undo the ``!r`` repr quoting record_step applies to ``retry_of``."""
    s = s.strip()
    for q in ("'", '"'):
        if len(s) >= 2 and s.startswith(q) and s.endswith(q):
            return s[1:-1]
    return s


# Cell content may contain an escaped pipe (`\|`), so split on unescaped
# delimiters only — splitting first and unescaping after would tear a cell
# in half at its own escaped pipe.
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


def _split_row(line: str) -> list[str]:
    m = TABLE_ROW_RE.match(line)
    if not m:
        return []
    return [
        c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE_RE.split(m.group("cells"))
    ]


def _parse_tables(lines: list[str]) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """Pull ``### title`` + pipe-table blocks out of an entry's body.

    Returns the tables and the lines that were *not* part of any table, so
    the caller can keep them as free-form details.
    """
    tables: dict[str, list[dict[str, str]]] = {}
    leftover: list[str] = []
    i = 0
    while i < len(lines):
        title_m = TABLE_TITLE_RE.match(lines[i])
        if not title_m:
            leftover.append(lines[i])
            i += 1
            continue

        # Look ahead past blank lines for a header row; a `###` heading with
        # no table under it is ordinary prose, not a table block.
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or not TABLE_ROW_RE.match(lines[j]):
            leftover.append(lines[i])
            i += 1
            continue

        columns = _split_row(lines[j])
        j += 1
        if j < len(lines) and TABLE_RULE_RE.match(lines[j]):
            j += 1
        rows: list[dict[str, str]] = []
        while j < len(lines) and TABLE_ROW_RE.match(lines[j]):
            cells = _split_row(lines[j])
            rows.append(
                {
                    col: (cells[k] if k < len(cells) else "")
                    for k, col in enumerate(columns)
                }
            )
            j += 1
        tables[title_m.group("title")] = rows
        i = j
    return tables, leftover


def _parse_entry_body(entry: Entry, body: list[str]) -> None:
    """Fill an entry's consultant fields, tables, and details from its body."""
    detail_lines: list[str] = []
    for line in body:
        retry_m = RETRY_OF_RE.match(line.strip())
        if retry_m and entry.retry_of is None:
            entry.retry_of = _strip_quotes(retry_m.group("title"))
            continue

        field_m = CONSULTANT_FIELD_RE.match(line)
        if field_m:
            key = FIELD_NAME_TO_KEY[field_m.group(1)]
            value = field_m.group(2).strip()
            if key == "why":
                cite_m = INLINE_CITES_RE.search(value)
                if cite_m:
                    entry.citations = [
                        c.strip() for c in cite_m.group(1).split(",") if c.strip()
                    ]
                    value = INLINE_CITES_RE.sub("", value).rstrip()
            # A rendered gap sentinel means the field was left empty.
            setattr(entry, key, "" if value in GAP_SENTINELS else value)
            continue

        # The <details> wrapper is structure, not content.
        stripped = line.strip()
        if stripped.startswith("<details") or stripped == "</details>":
            continue
        detail_lines.append(line)

    entry.tables, leftover = _parse_tables(detail_lines)
    entry.details = "\n".join(leftover).strip()


def _parse_banner(text: str) -> Banner | None:
    if SUMMARY_BEGIN not in text or SUMMARY_END not in text:
        return None
    block = text.split(SUMMARY_BEGIN, 1)[1].split(SUMMARY_END, 1)[0]
    verdict, outcome = "", ""
    steps = decisions = retries = gaps = 0
    for line in block.splitlines():
        v_m = VERDICT_RE.match(line.strip())
        if v_m:
            verdict = v_m.group("verdict")
            outcome = v_m.group("outcome").strip()
            continue
        c_m = COUNTS_RE.search(line)
        if c_m:
            steps = int(c_m.group("steps"))
            decisions = int(c_m.group("decisions"))
            retries = int(c_m.group("retries"))
            gaps = int(c_m.group("gaps"))
    if not verdict:
        return None
    return Banner(verdict, outcome, steps, decisions, retries, gaps)


def _parse_decisions_index(text: str) -> list[dict[str, str]]:
    if DECISIONS_BEGIN not in text or DECISIONS_END not in text:
        return []
    block = text.split(DECISIONS_BEGIN, 1)[1].split(DECISIONS_END, 1)[0]
    lines = block.splitlines()
    tables, _ = _parse_tables(["### Decisions", *lines])
    rows = tables.get("Decisions", [])
    if rows:
        # The index is machine-generated with title-case headers; lowercase
        # them so consumers can index it without guessing the casing.
        return [{k.strip().lower(): v for k, v in row.items()} for row in rows]
    # The index renders as `## Decisions` + a bare table, so re-try without
    # relying on a `###` heading.
    header_idx = next((i for i, ln in enumerate(lines) if TABLE_ROW_RE.match(ln)), None)
    if header_idx is None:
        return []
    columns = _split_row(lines[header_idx])
    out: list[dict[str, str]] = []
    for ln in lines[header_idx + 1 :]:
        if TABLE_RULE_RE.match(ln):
            continue
        if not TABLE_ROW_RE.match(ln):
            break
        cells = _split_row(ln)
        out.append(
            {
                col.strip().lower(): (cells[k] if k < len(cells) else "")
                for k, col in enumerate(columns)
            }
        )
    return out


def parse_report_text(text: str, path: Path | None = None) -> Report:
    """Parse ``REPORT.md`` content into a :class:`Report`."""
    banner = _parse_banner(text)
    decisions_index = _parse_decisions_index(text)

    # Drop the generated blocks before walking entries so their table rows
    # never register as entry content.
    body = text
    for begin, end in ((SUMMARY_BEGIN, SUMMARY_END), (DECISIONS_BEGIN, DECISIONS_END)):
        if begin in body and end in body:
            head, rest = body.split(begin, 1)
            body = head + rest.split(end, 1)[1]

    entries: list[Entry] = []
    current: Entry | None = None
    current_body: list[str] = []

    for idx, line in enumerate(body.splitlines(), start=1):
        header_m = ENTRY_HEADER_RE.match(line)
        if header_m:
            if current is not None:
                _parse_entry_body(current, current_body)
                entries.append(current)
            current = Entry(
                timestamp=header_m.group("ts"),
                phase=header_m.group("phase").strip(),
                status=header_m.group("status").strip(),
                title=header_m.group("title").strip(),
                line_no=idx,
                pending_review=bool(header_m.group("pending")),
            )
            current_body = []
            continue
        if current is not None:
            current_body.append(line)

    if current is not None:
        _parse_entry_body(current, current_body)
        entries.append(current)

    return Report(
        path=path,
        entries=entries,
        banner=banner,
        decisions_index=decisions_index,
        finalized=banner is not None,
    )


def parse_report(path: str | Path) -> Report:
    """Parse a ``REPORT.md`` from disk. Missing file → an empty report."""
    p = Path(path)
    if p.is_dir():
        p = p / "REPORT.md"
    if not p.is_file():
        return Report(path=p, entries=[])
    return parse_report_text(p.read_text(errors="replace"), path=p)
