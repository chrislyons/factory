# DEPRECATED — 2026-03-20
# This script parsed FCT012 markdown into tasks.json. The task tracking system
# has migrated to individual YAML job files in jobs/. Use build-jobs-json.py instead.
# Retained for historical reference only.
#!/usr/bin/env python3
"""Parse FCT012 markdown tables into tasks.json for the Factory portal GSD sidecar.

Usage:
    python3 scripts/sync-fct012.py              # write tasks.json
    python3 scripts/sync-fct012.py --dry-run    # summary only
    python3 scripts/sync-fct012.py -o path.json # custom output
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FACTORY_ROOT = Path(__file__).resolve().parent.parent
FCT012_PATH = FACTORY_ROOT / "docs" / "fct" / "FCT012 Factory — Task Backlog and Work Item Registry.md"
DEFAULT_OUTPUT = FACTORY_ROOT / "tasks.json"

# Section heading text -> block id + colour (portal v8 palette)
SECTION_MAP: dict[str, tuple[str, str, str]] = {
    # heading fragment -> (block_id, label, colour)
    "Infrastructure": ("infrastructure", "Infrastructure", "#6366f1"),
    "Agent Capabilities": ("agent-capabilities", "Agent Capabilities", "#38bdf8"),
    "Agent Loops": ("agent-loops", "Agent Loops", "#f97316"),
    "Portal UX": ("portal-ux", "Portal UX", "#a78bfa"),
    "Research and Exploration": ("research-exploration", "Research and Exploration", "#fb7185"),
    "Coordinator-rs": ("coordinator-rs", "Coordinator-rs", "#34d399"),
    "GSD Legacy": ("gsd-legacy", "GSD Legacy", "#71717a"),
    "Curriculum-Derived Work Items": ("curriculum-derived", "Curriculum-Derived", "#fbbf24"),
    "Completed Items": ("completed", "Completed", "#4ade80"),
}

STATUS_MAP: dict[str, str] = {
    "todo": "pending",
    "in-progress": "in-progress",
    "done": "done",
    "blocked": "blocked",
    "deferred": "pending",
}

EFFORT_MAP: dict[str, str] = {
    "xs": "low",
    "s": "low",
    "m": "medium",
    "l": "high",
    "xl": "high",
}

# Em-dash variants
EM_DASHES = {"\u2014", "---", "\u2013"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_backticks(s: str) -> str:
    """Remove surrounding backticks from a value."""
    return s.strip().strip("`").strip()


def normalise_id(raw: str) -> str:
    """FCT-001 -> fct-001, lowercase."""
    return raw.strip().lower()


def is_em_dash(s: str) -> bool:
    """Check if a string is an em-dash variant."""
    stripped = s.strip()
    return stripped in EM_DASHES or stripped == "—"


def map_status(raw: str) -> str:
    key = strip_backticks(raw).lower()
    return STATUS_MAP.get(key, "pending")


def map_effort(raw: str) -> str:
    key = strip_backticks(raw).lower()
    return EFFORT_MAP.get(key, "medium")


def parse_deps(raw: str) -> list[str]:
    """Parse comma-separated dependency IDs. Em-dash or blank -> []."""
    stripped = strip_backticks(raw)
    if not stripped or is_em_dash(stripped):
        return []
    parts = re.split(r"[,;]\s*", stripped)
    return [normalise_id(p) for p in parts if p.strip() and not is_em_dash(p)]


def detect_section(heading: str) -> tuple[str, str, str] | None:
    """Match a heading line to a known section. Returns (block_id, label, colour) or None."""
    for fragment, info in SECTION_MAP.items():
        if fragment.lower() in heading.lower():
            return info
    return None


def parse_table_row(line: str) -> list[str] | None:
    """Parse a markdown table row into cells. Returns None for separator rows."""
    line = line.strip()
    if not line.startswith("|"):
        return None
    # Separator row (|---|---|...)
    if re.match(r"^\|[\s\-:|]+\|$", line):
        return None
    cells = [c.strip() for c in line.split("|")]
    # Split produces empty strings at start/end due to leading/trailing |
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells if cells else None


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def parse_standard_row(cells: list[str], block_id: str, order: int) -> dict | None:
    """Parse an 8-column standard row (sections 2-7)."""
    if len(cells) < 8:
        return None
    raw_id, title, status, priority, effort, owner, deps, notes = (
        cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], cells[7]
    )
    task_id = normalise_id(raw_id)
    if not task_id or is_em_dash(task_id):
        return None  # Skip header-like rows
    return {
        "id": task_id,
        "title": strip_backticks(title),
        "description": strip_backticks(notes) if notes.strip() and not is_em_dash(notes) else None,
        "status": map_status(status),
        "effort": map_effort(effort),
        "order": order,
        "blocked_by": parse_deps(deps),
        "block": block_id,
        "assignee": strip_backticks(owner) if owner.strip() and not is_em_dash(owner) else None,
    }


def parse_completed_row(cells: list[str], order: int, done_counter: int) -> tuple[dict | None, int]:
    """Parse a 4-column completed row (section 8). Returns (task, updated_counter)."""
    if len(cells) < 4:
        return None, done_counter
    raw_id, title, status, closed_by = cells[0], cells[1], cells[2], cells[3]
    # Generate synthetic ID for em-dash IDs
    if is_em_dash(raw_id.strip()):
        done_counter += 1
        task_id = f"fct-done-{done_counter:03d}"
    else:
        task_id = normalise_id(raw_id)
    if not strip_backticks(title):
        return None, done_counter
    desc = f"Closed by {strip_backticks(closed_by)}" if closed_by.strip() and not is_em_dash(closed_by) else None
    return {
        "id": task_id,
        "title": strip_backticks(title),
        "description": desc,
        "status": "done",
        "effort": None,
        "order": order,
        "blocked_by": [],
        "block": "completed",
        "assignee": None,
    }, done_counter


def parse_gsd_row(cells: list[str], block_id: str, order: int) -> dict | None:
    """Parse a 7-column GSD legacy row (section 9, no Deps column)."""
    if len(cells) < 7:
        return None
    raw_id, title, status, priority, effort, owner, notes = (
        cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6]
    )
    task_id = normalise_id(raw_id)
    if not task_id or is_em_dash(task_id):
        return None
    return {
        "id": task_id,
        "title": strip_backticks(title),
        "description": strip_backticks(notes) if notes.strip() and not is_em_dash(notes) else None,
        "status": map_status(status),
        "effort": map_effort(effort),
        "order": order,
        "blocked_by": [],
        "block": block_id,
        "assignee": strip_backticks(owner) if owner.strip() and not is_em_dash(owner) else None,
    }


def parse_curriculum_row(cells: list[str], block_id: str, order: int) -> dict | None:
    """Parse a 7-column curriculum row (section 10: ID,Title,Status,Priority,Effort,Source Module,Notes)."""
    if len(cells) < 7:
        return None
    raw_id, title, status, priority, effort, source, notes = (
        cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6]
    )
    task_id = normalise_id(raw_id)
    if not task_id or is_em_dash(task_id):
        return None
    # Combine source module and notes into description
    desc_parts = []
    if source.strip() and not is_em_dash(source):
        desc_parts.append(f"Source: {strip_backticks(source)}")
    if notes.strip() and not is_em_dash(notes):
        desc_parts.append(strip_backticks(notes))
    desc = ". ".join(desc_parts) if desc_parts else None
    return {
        "id": task_id,
        "title": strip_backticks(title),
        "description": desc,
        "status": map_status(status),
        "effort": map_effort(effort),
        "order": order,
        "blocked_by": [],
        "block": block_id,
        "assignee": None,
    }


# ---------------------------------------------------------------------------
# Detect column layout from header row
# ---------------------------------------------------------------------------

LAYOUT_STANDARD = "standard"   # 8 cols: ID,Title,Status,Priority,Effort,Owner,Deps,Notes
LAYOUT_COMPLETED = "completed" # 4 cols: ID,Title,Status,Closed By
LAYOUT_GSD = "gsd"             # 7 cols, no Deps
LAYOUT_CURRICULUM = "curriculum"  # 7 cols, Source Module instead of Owner+Deps


def detect_layout(header_cells: list[str]) -> str:
    """Detect table layout from the header row cells."""
    ncols = len(header_cells)
    headers_lower = [c.strip().lower() for c in header_cells]
    if ncols == 4 and "closed" in " ".join(headers_lower):
        return LAYOUT_COMPLETED
    if ncols >= 8:
        return LAYOUT_STANDARD
    if ncols == 7 and "source" in " ".join(headers_lower):
        return LAYOUT_CURRICULUM
    if ncols == 7:
        return LAYOUT_GSD
    # Fallback: try standard if >= 8 else skip
    return LAYOUT_STANDARD if ncols >= 8 else LAYOUT_GSD


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_fct012(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """Parse FCT012 markdown into (tasks, blocks)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    tasks: list[dict] = []
    blocks: dict[str, dict] = {}
    seen_ids: set[str] = set()
    order = 0
    done_counter = 0

    current_block: tuple[str, str, str] | None = None
    in_table = False
    layout: str | None = None
    header_seen = False

    for line in lines:
        stripped = line.strip()

        # Detect section headings (## N. Title or ## Title)
        heading_match = re.match(r"^##\s+(?:\d+\.\s+)?(.+)$", stripped)
        if heading_match:
            heading_text = heading_match.group(1).strip()
            detected = detect_section(heading_text)
            if detected:
                current_block = detected
                block_id, label, colour = detected
                blocks[block_id] = {"label": label, "color": colour}
                in_table = False
                header_seen = False
                layout = None
            else:
                current_block = None
                in_table = False
            continue

        if current_block is None:
            continue

        block_id, label, colour = current_block

        # Table rows
        if stripped.startswith("|"):
            cells = parse_table_row(stripped)
            if cells is None:
                # Separator row — marks that header was consumed
                continue

            # First non-separator row after heading is the header
            if not header_seen:
                header_seen = True
                layout = detect_layout(cells)
                continue

            # Data row
            task = None
            if layout == LAYOUT_COMPLETED:
                task, done_counter = parse_completed_row(cells, order, done_counter)
            elif layout == LAYOUT_CURRICULUM:
                task = parse_curriculum_row(cells, block_id, order)
            elif layout == LAYOUT_GSD:
                task = parse_gsd_row(cells, block_id, order)
            else:
                task = parse_standard_row(cells, block_id, order)

            if task and task["id"] not in seen_ids:
                seen_ids.add(task["id"])
                order += 1
                task["order"] = order
                tasks.append(task)

    return tasks, blocks


def build_document(tasks: list[dict], blocks: dict[str, dict]) -> dict:
    """Build a TasksDocument-compatible JSON structure."""
    now = datetime.now(timezone.utc).isoformat()
    # Clean up None values in tasks to match TypeScript optional fields
    clean_tasks = []
    for t in tasks:
        clean = {k: v for k, v in t.items() if v is not None}
        # Ensure required fields always present
        clean.setdefault("blocked_by", [])
        clean.setdefault("order", 0)
        clean_tasks.append(clean)

    return {
        "tasks": clean_tasks,
        "blocks": blocks,
        "log": [],
        "updated": now,
        "updated_by": "sync-fct012.py",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Sync FCT012 markdown to tasks.json")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output path")
    parser.add_argument("--input", type=Path, default=FCT012_PATH, help="FCT012 markdown path")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    tasks, blocks = parse_fct012(args.input)
    doc = build_document(tasks, blocks)

    if args.dry_run:
        print(f"Parsed {len(tasks)} tasks across {len(blocks)} blocks:\n")
        for block_id, info in blocks.items():
            count = sum(1 for t in tasks if t.get("block") == block_id)
            print(f"  {info['label']:.<35} {count:>3} items  {info['color']}")
        print()
        by_status: dict[str, int] = {}
        for t in tasks:
            s = t.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
        print("By status:")
        for s, c in sorted(by_status.items()):
            print(f"  {s:.<20} {c:>3}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(tasks)} tasks, {len(blocks)} blocks to {args.output}")


if __name__ == "__main__":
    main()
