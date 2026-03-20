#!/usr/bin/env python3
"""One-time migration: tasks.json -> jobs/ YAML files.

Usage:
    python3 scripts/migrate-tasks-to-jobs.py           # run migration
    python3 scripts/migrate-tasks-to-jobs.py --dry-run  # preview only
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import yaml


# ---------------------------------------------------------------------------
# YAML string representer — use block style for long strings
# ---------------------------------------------------------------------------
def str_representer(dumper, data):
    if "\n" in data or len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_representer)

FACTORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_JSON = os.path.join(FACTORY_ROOT, "tasks.json")
REGISTRY_YAML = os.path.join(FACTORY_ROOT, "jobs", "registry.yaml")
JOBS_DIR = os.path.join(FACTORY_ROOT, "jobs")
TODAY = "2026-03-20"

# ---------------------------------------------------------------------------
# Domain mapping (from assignee)
# ---------------------------------------------------------------------------
ASSIGNEE_TO_DOMAIN = {
    "chris": "00",
    "boot": "10",
    "ig88": "20",
    "kelk": "30",
}

# ---------------------------------------------------------------------------
# Class mapping (from block)
# ---------------------------------------------------------------------------
BLOCK_TO_CLASS = {
    "infrastructure": "001",
    "agent-capabilities": "002",
    "agent-loops": "003",
    "portal-ux": "004",
    "research-exploration": "005",
    "coordinator-rs": "006",
    "gsd-legacy": "007",
    "curriculum-derived": "008",
}

# ---------------------------------------------------------------------------
# Completed task classification rules
# ---------------------------------------------------------------------------
COMPLETED_CLASS_RULES = [
    # (pattern, class, domain_override)
    (r"(?i)(coordinator|loop_engine|task_lease|approval|budget|context_mode|ContextMode|runtime_state|run_events|RunEvent|LoopSpec|LoopManager|LoopConfig|build_loop_context|LoopIteration|InfraChange)", "006", "10"),
    (r"(?i)(Portal|portal)", "004", "10"),
    (r"(?i)(GSD|dashboard)", "007", "00"),
    (r"(?i)(trust level|branding rename|Relay loop)", "001", "10"),
    (r"(?i)(Paperclip|pattern)", "008", "00"),
]

# ---------------------------------------------------------------------------
# IDs to cull (skip entirely)
# ---------------------------------------------------------------------------
CULL_IDS = {"fct-085", "fct-086", "fct-087"}

# ---------------------------------------------------------------------------
# IDs to flag as deferred + needs-scoping
# ---------------------------------------------------------------------------
DEFER_IDS = {"fct-045", "fct-046", "fct-047", "fct-048", "fct-049", "fct-050", "fct-051"}


def classify_completed(title):
    """Determine (class, domain) for a completed task based on title."""
    for pattern, cls, domain in COMPLETED_CLASS_RULES:
        if re.search(pattern, title):
            return cls, domain
    return "001", "10"  # default fallback


def apply_audit(task):
    """Apply audit findings to a task dict (mutates in place). Returns False if task should be culled."""
    tid = task["id"]

    # Cull
    if tid in CULL_IDS:
        return False

    # Mark as DONE
    if tid == "fct-055":
        task["status"] = "done"
        task["completed"] = "2026-03-20"
        task["closed_by"] = "ATR005/codebase-verified"

    if tid == "fct-010":
        task["status"] = "done"
        task["completed"] = "2026-03-20"
        task["closed_by"] = "FCT014/port-reorg"

    # Update descriptions
    if tid == "fct-001":
        task["description"] += " Partially complete — Cloudkicker migrated to Bitwarden (BKX121). Blackbox retains age encryption by design."

    if tid == "fct-007":
        task["title"] = "Verify @coord:matrix.org coordinator identity"
        task["description"] = "@coord:matrix.org identity exists (BKX083). Verify it is the active coordinator identity and close if confirmed."

    if tid == "fct-002":
        task["description"] += " Core audit complete (BKX029, BKX071). Two MEDIUM items deferred: qdrant-mcp bridge caller auth, LLM failover context sanitization."

    if tid == "fct-003":
        task["description"] += " Tailscale ACL audit complete (BKX070/071). ACL applied manually via admin console. manage_acl MCP tool confirmed unsafe for updates."

    if tid == "fct-040":
        task["title"] = task["title"].replace(":41935", ":41911")
        task["description"] = task["description"].replace("41935", "41911")

    # Fix dependencies
    if tid == "fct-027":
        task["blocked_by"] = []

    if tid == "fct-028":
        task["blocked_by"] = []

    # Remove fct-055 from any blocked_by (it's now done)
    if "blocked_by" in task and "fct-055" in task.get("blocked_by", []):
        task["blocked_by"] = [x for x in task["blocked_by"] if x != "fct-055"]

    # Flag for review
    if tid in DEFER_IDS:
        task["status"] = "deferred"
        task.setdefault("tags", [])
        if "needs-scoping" not in task["tags"]:
            task["tags"].append("needs-scoping")

    # Fix completed task descriptions
    if tid == "fct-done-005":
        task["title"] = "Implement ContextMode enum in config.rs (not standalone file)"

    if tid == "fct-done-019":
        task["title"] = task["title"].replace(":41988", ":41910")

    return True


def build_job_yaml(task, job_id, new_blocked_by):
    """Build the YAML dict for a single job."""
    doc = {
        "id": job_id,
        "title": task["title"],
        "status": task["status"],
        "priority": task.get("priority", f'p{2 if task.get("effort") in ("medium", "high") else 3 if not task.get("effort") else 2}'),
        "effort": task.get("effort", "low"),
        "assignee": task.get("assignee", "chris"),
        "blocked_by": new_blocked_by,
        "description": task.get("description", ""),
        "tags": task.get("tags", []),
        "created": TODAY,
        "updated": TODAY,
        "legacy_id": task["id"],
    }

    # Priority heuristic: done=p3, effort-based otherwise
    if task["status"] == "done":
        doc["priority"] = "p3"
    elif task.get("effort") == "high":
        doc["priority"] = "p1"
    elif task.get("effort") == "medium":
        doc["priority"] = "p2"
    else:
        doc["priority"] = "p3"

    # For done items
    if task["status"] == "done":
        doc["completed"] = task.get("completed", TODAY)
        doc["closed_by"] = task.get("closed_by", task.get("description", "").replace("Closed by ", ""))

    return doc


def main():
    parser = argparse.ArgumentParser(description="Migrate tasks.json to jobs/ YAML")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    # Load inputs
    with open(TASKS_JSON) as f:
        data = json.load(f)

    with open(REGISTRY_YAML) as f:
        registry = yaml.safe_load(f)

    tasks = data["tasks"]

    # Phase 1: Apply audit and classify
    processed = []
    for task in tasks:
        task = dict(task)  # copy
        if not apply_audit(task):
            print(f"  CULLED: {task['id']} — {task['title'][:60]}")
            continue
        processed.append(task)

    # Phase 2: Determine domain + class for each task
    for task in processed:
        block = task.get("block", "infrastructure")
        assignee = task.get("assignee", "chris") or "chris"

        if block == "completed":
            cls, domain = classify_completed(task["title"])
        else:
            cls = BLOCK_TO_CLASS.get(block, "001")
            domain = ASSIGNEE_TO_DOMAIN.get(assignee, "00")

        task["_domain"] = domain
        task["_class"] = cls

    # Phase 3: Auto-increment addresses per (domain, class)
    counters = defaultdict(int)
    migration_map = {}

    for task in processed:
        domain = task["_domain"]
        cls = task["_class"]
        key = (domain, cls)
        counters[key] += 1
        addr = f"{counters[key]:04d}"
        job_id = f"job.{domain}.{cls}.{addr}"
        task["_job_id"] = job_id
        migration_map[task["id"]] = job_id

    # Phase 4: Rewrite blocked_by using migration map
    job_docs = []
    for task in processed:
        old_deps = task.get("blocked_by", [])
        new_deps = []
        for dep in old_deps:
            if dep in migration_map:
                new_deps.append(migration_map[dep])
            else:
                print(f"  WARNING: {task['id']} has dep {dep} not in migration map (culled?), dropping")
        job_doc = build_job_yaml(task, task["_job_id"], new_deps)
        job_docs.append((task["_domain"], job_doc))

    # Summary
    domain_counts = defaultdict(int)
    class_counts = defaultdict(int)
    for domain, doc in job_docs:
        domain_counts[domain] += 1
        cls = doc["id"].split(".")[2]
        class_label = registry["classes"].get(cls, {}).get("label", cls)
        class_counts[class_label] += 1

    print(f"\n=== Migration Summary ===")
    print(f"Total jobs: {len(job_docs)}")
    print(f"\nBy domain:")
    for d in sorted(domain_counts):
        label = registry["domains"].get(d, {}).get("label", d)
        print(f"  {d} ({label}): {domain_counts[d]}")
    print(f"\nBy class:")
    for c in sorted(class_counts):
        print(f"  {c}: {class_counts[c]}")
    print(f"\nCulled: {len(tasks) - len(processed)}")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        print("\nMigration map:")
        for old, new in migration_map.items():
            print(f"  {old} -> {new}")
        return

    # Phase 5: Write files
    # Create domain directories
    for domain in sorted(set(d for d, _ in job_docs)):
        os.makedirs(os.path.join(JOBS_DIR, domain), exist_ok=True)

    for domain, doc in job_docs:
        filename = f"{doc['id']}.yaml"
        filepath = os.path.join(JOBS_DIR, domain, filename)
        with open(filepath, "w") as f:
            yaml.dump(doc, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"  wrote {filepath}")

    # Write migration map
    map_path = os.path.join(JOBS_DIR, "migration-map.yaml")
    with open(map_path, "w") as f:
        yaml.dump(migration_map, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"\n  wrote {map_path}")

    print(f"\nMigration complete. {len(job_docs)} job files created.")


if __name__ == "__main__":
    main()
