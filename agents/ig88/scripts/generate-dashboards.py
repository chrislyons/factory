#!/usr/bin/env python3
"""
Agent Activity Dashboard Generator
====================================
Queries Graphiti for recent facts/episodes per agent and generates
Obsidian-compatible JSON Canvas files for visual dashboards.

Dashboard types:
  - Brain map: Entity relationships and knowledge clusters
  - Activity timeline: Recent observations by category

Usage:
    python3 generate-dashboards.py              # Generate all dashboards
    python3 generate-dashboards.py --group ACX  # Generate for specific group
    python3 generate-dashboards.py --dry-run    # Preview without writing

Output: ~/dev/claude-vault/dashboards/
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

GRAPHITI_URL = os.environ.get("GRAPHITI_URL", "http://100.88.222.111:41440")
VAULT_PATH = Path(os.environ.get("VAULT_PATH", os.path.expanduser("~/dev/claude-vault")))
DASHBOARD_DIR = VAULT_PATH / "dashboards"

# Observation category colors for canvas nodes
CATEGORY_COLORS = {
    "decision": "4",    # Green
    "lesson": "5",      # Cyan
    "preference": "6",  # Purple
    "milestone": "1",   # Red (celebration)
    "commitment": "3",  # Yellow
    "context": "0",     # Default
}

# Group IDs to query
DEFAULT_GROUPS = ["system", "IG88", "ACX", "HBX", "WBD", "ORP", "HLM", "OND", "CLZ", "LMK"]


def fetch_json(url: str) -> dict | list | None:
    """Fetch JSON from URL using urllib (no external deps)."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"  Warning: Failed to fetch {url}: {e}")
        return None


def post_json(url: str, data: dict) -> dict | list | None:
    """POST JSON to URL using urllib."""
    import urllib.request
    import urllib.error

    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"  Warning: Failed to POST {url}: {e}")
        return None


def fetch_recent_episodes(group_id: str, limit: int = 50) -> list:
    """Fetch recent episodes from Graphiti for a group."""
    result = post_json(f"{GRAPHITI_URL}/search", {
        "query": "recent activity observations decisions",
        "group_ids": [group_id],
        "num_results": limit,
    })
    if result and isinstance(result, list):
        return result
    # Fallback: try episodes endpoint
    result = fetch_json(f"{GRAPHITI_URL}/episodes?group_id={group_id}&limit={limit}")
    if result and isinstance(result, list):
        return result
    return []


def fetch_entity_nodes(group_id: str, query: str = "entities", limit: int = 30) -> list:
    """Search for entity nodes in the knowledge graph."""
    result = post_json(f"{GRAPHITI_URL}/search/nodes", {
        "query": query,
        "group_ids": [group_id],
        "num_results": limit,
    })
    if result and isinstance(result, list):
        return result
    return []


def fetch_facts(group_id: str, query: str = "decisions and relationships", limit: int = 30) -> list:
    """Search for facts (relationships) in the knowledge graph."""
    result = post_json(f"{GRAPHITI_URL}/search/facts", {
        "query": query,
        "group_ids": [group_id],
        "num_results": limit,
    })
    if result and isinstance(result, list):
        return result
    return []


def classify_observation(text: str) -> str:
    """Classify an observation by category from its content."""
    lower = text.lower()
    if lower.startswith("[decision]") or "decided" in lower or "decision:" in lower:
        return "decision"
    elif lower.startswith("[lesson]") or "learned" in lower or "lesson:" in lower:
        return "lesson"
    elif lower.startswith("[preference]") or "prefer" in lower or "preference:" in lower:
        return "preference"
    elif lower.startswith("[milestone]") or "completed" in lower or "milestone:" in lower:
        return "milestone"
    elif lower.startswith("[commitment]") or "will " in lower[:20] or "commitment:" in lower:
        return "commitment"
    else:
        return "context"


def generate_activity_canvas(group_id: str, episodes: list) -> dict:
    """Generate an activity timeline canvas from episodes."""
    nodes = []
    edges = []

    # Title node
    nodes.append({
        "id": "title",
        "type": "text",
        "x": 0,
        "y": -200,
        "width": 400,
        "height": 80,
        "text": f"# {group_id} Activity Dashboard\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    })

    # Category column headers
    categories = ["decision", "lesson", "preference", "milestone", "commitment", "context"]
    col_width = 350
    col_gap = 50
    start_x = -((len(categories) * (col_width + col_gap)) // 2)

    for i, cat in enumerate(categories):
        x = start_x + i * (col_width + col_gap)
        header_id = f"header-{cat}"
        nodes.append({
            "id": header_id,
            "type": "text",
            "x": x,
            "y": 0,
            "width": col_width,
            "height": 60,
            "color": CATEGORY_COLORS.get(cat, "0"),
            "text": f"## {cat.title()}s",
        })

    # Place episodes in category columns
    category_counts: dict[str, int] = {cat: 0 for cat in categories}

    for ep in episodes:
        content = ep.get("episode_body", ep.get("content", ep.get("body", "")))
        name = ep.get("name", "")
        if not content and not name:
            continue

        display_text = name or content[:200]
        cat = classify_observation(display_text)
        col_idx = categories.index(cat) if cat in categories else len(categories) - 1
        row = category_counts[cat]
        category_counts[cat] += 1

        x = start_x + col_idx * (col_width + col_gap)
        y = 100 + row * 120

        node_id = f"ep-{cat}-{row}"
        nodes.append({
            "id": node_id,
            "type": "text",
            "x": x,
            "y": y,
            "width": col_width,
            "height": 100,
            "color": CATEGORY_COLORS.get(cat, "0"),
            "text": display_text[:300],
        })

        # Edge from header to node
        edges.append({
            "id": f"edge-{node_id}",
            "fromNode": f"header-{cat}",
            "fromSide": "bottom",
            "toNode": node_id,
            "toSide": "top",
        })

    return {"nodes": nodes, "edges": edges}


def generate_brain_canvas(group_id: str, entities: list, facts: list) -> dict:
    """Generate a brain map canvas from entity nodes and facts."""
    nodes = []
    edges = []

    # Title
    nodes.append({
        "id": "brain-title",
        "type": "text",
        "x": 0,
        "y": -300,
        "width": 500,
        "height": 80,
        "text": f"# {group_id} Knowledge Graph\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    })

    # Place entity nodes in a circle
    import math
    entity_map: dict[str, str] = {}  # uuid -> node_id

    for i, entity in enumerate(entities[:20]):  # Cap at 20 nodes
        name = entity.get("name", f"Entity {i}")
        summary = entity.get("summary", "")
        uuid = entity.get("uuid", str(i))

        angle = (2 * math.pi * i) / min(len(entities), 20)
        radius = 500
        x = int(radius * math.cos(angle))
        y = int(radius * math.sin(angle))

        node_id = f"entity-{i}"
        entity_map[uuid] = node_id

        nodes.append({
            "id": node_id,
            "type": "text",
            "x": x,
            "y": y,
            "width": 280,
            "height": 120,
            "color": "4",
            "text": f"### {name}\n\n{summary[:200]}" if summary else f"### {name}",
        })

    # Add fact edges
    for i, fact in enumerate(facts[:30]):  # Cap at 30 edges
        subject = fact.get("subject_id", "")
        obj = fact.get("object_id", "")
        predicate = fact.get("predicate", fact.get("fact", "related to"))

        from_node = entity_map.get(subject)
        to_node = entity_map.get(obj)

        if from_node and to_node and from_node != to_node:
            edges.append({
                "id": f"fact-{i}",
                "fromNode": from_node,
                "fromSide": "right",
                "toNode": to_node,
                "toSide": "left",
                "label": str(predicate)[:50] if predicate else None,
            })

    return {"nodes": nodes, "edges": edges}


def write_canvas(filepath: Path, canvas: dict) -> None:
    """Write a JSON Canvas file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(canvas, f, indent=2)
    print(f"  Written: {filepath}")


def main():
    dry_run = "--dry-run" in sys.argv
    target_group = None
    for i, arg in enumerate(sys.argv):
        if arg == "--group" and i + 1 < len(sys.argv):
            target_group = sys.argv[i + 1].upper()

    groups = [target_group] if target_group else DEFAULT_GROUPS

    print("Agent Activity Dashboard Generator")
    print("===================================")
    print(f"Graphiti: {GRAPHITI_URL}")
    print(f"Output: {DASHBOARD_DIR}")
    print(f"Groups: {', '.join(groups)}")
    print()

    # Test Graphiti connectivity
    status = fetch_json(f"{GRAPHITI_URL}/healthcheck")
    if status is None:
        # Try alternate health endpoint
        status = fetch_json(f"{GRAPHITI_URL}/status")
    if status is None:
        print("Warning: Could not reach Graphiti. Generating placeholder dashboards.")

    for group_id in groups:
        print(f"\n[{group_id}]")

        # Fetch data
        episodes = fetch_recent_episodes(group_id)
        entities = fetch_entity_nodes(group_id)
        facts = fetch_facts(group_id)

        print(f"  Episodes: {len(episodes)}, Entities: {len(entities)}, Facts: {len(facts)}")

        if dry_run:
            print(f"  [DRY RUN] Would generate activity + brain canvases")
            continue

        # Generate activity timeline
        if episodes:
            activity = generate_activity_canvas(group_id, episodes)
            write_canvas(
                DASHBOARD_DIR / f"{group_id.lower()}-activity.canvas",
                activity,
            )

        # Generate brain map
        if entities:
            brain = generate_brain_canvas(group_id, entities, facts)
            write_canvas(
                DASHBOARD_DIR / f"{group_id.lower()}-brain.canvas",
                brain,
            )

        if not episodes and not entities:
            print(f"  No data available for {group_id}")

    print("\nDone!")
    if not dry_run:
        print(f"Dashboards available in: {DASHBOARD_DIR}")
        print("Open in Obsidian to view canvas visualizations.")


if __name__ == "__main__":
    main()
