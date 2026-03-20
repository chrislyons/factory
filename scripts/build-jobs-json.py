#!/usr/bin/env python3
"""Build jobs.json from jobs/ YAML files for portal consumption.

Replaces sync-fct012.py. Reads job YAML files and registry, produces
a JSON document matching the TasksDocument interface.

Usage:
    python3 scripts/build-jobs-json.py                    # write to jobs.json
    python3 scripts/build-jobs-json.py -o /path/out.json  # custom output
    python3 scripts/build-jobs-json.py --dry-run           # preview only
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

import yaml

FACTORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_YAML = os.path.join(FACTORY_ROOT, "jobs", "registry.yaml")
JOBS_DIR = os.path.join(FACTORY_ROOT, "jobs")
DEFAULT_OUTPUT = os.path.join(FACTORY_ROOT, "jobs.json")


def parse_job_id(job_id):
    """Parse job.DD.CCC.AAAA into (domain, class, address) as strings."""
    parts = job_id.split(".")
    return parts[1], parts[2], parts[3]


def sort_key(job):
    """Sort by domain (numeric), then class (numeric), then address (numeric)."""
    domain, cls, addr = parse_job_id(job["id"])
    return (int(domain), int(cls), int(addr))


def main():
    parser = argparse.ArgumentParser(description="Build jobs.json from jobs/ YAML files")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="Output path (default: jobs.json)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    # Load registry
    with open(REGISTRY_YAML) as f:
        registry = yaml.safe_load(f)

    # Build class label lookup (class code -> lowercase label)
    class_labels = {}
    for code, info in registry["classes"].items():
        class_labels[code] = info["label"].lower()

    # Build blocks map for output
    blocks = {}
    for code, info in registry["classes"].items():
        key = info["label"].lower()
        blocks[key] = {"label": info["label"], "color": info["color"]}

    # Walk job YAML files
    pattern = os.path.join(JOBS_DIR, "*", "job.*.yaml")
    job_files = glob.glob(pattern)

    if not job_files:
        print("ERROR: No job files found.", file=sys.stderr)
        sys.exit(1)

    jobs = []
    errors = []
    for filepath in job_files:
        try:
            with open(filepath) as f:
                doc = yaml.safe_load(f)
        except Exception as e:
            errors.append(f"{filepath}: {e}")
            continue

        domain, cls, addr = parse_job_id(doc["id"])
        block_label = class_labels.get(cls, "unknown")

        task = {
            "id": doc["id"],
            "title": doc["title"],
            "description": doc.get("description", ""),
            "status": doc["status"],
            "effort": doc.get("effort", "low"),
            "order": 0,  # filled after sort
            "blocked_by": doc.get("blocked_by", []),
            "block": block_label,
            "assignee": doc.get("assignee", "chris"),
            "domain": domain,
            "job_class": cls,
        }
        jobs.append(task)

    # Sort and assign order
    jobs.sort(key=sort_key)
    for i, job in enumerate(jobs, 1):
        job["order"] = i

    now = datetime.now(timezone.utc).isoformat()

    # Build registry maps for portal consumption
    registry_domains = {}
    for code, info in registry["domains"].items():
        registry_domains[code] = {
            "label": info["label"],
            "description": info.get("description", ""),
        }

    registry_classes = {}
    for code, info in registry["classes"].items():
        registry_classes[code] = {
            "label": info["label"],
            "color": info["color"],
        }

    output = {
        "tasks": jobs,
        "blocks": blocks,
        "log": [],
        "updated": now,
        "updated_by": "build-jobs-json.py",
        "registry": {
            "domains": registry_domains,
            "classes": registry_classes,
        },
    }

    # Summary
    print(f"Jobs found: {len(jobs)}")
    print(f"Errors: {len(errors)}")
    for e in errors:
        print(f"  ERROR: {e}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would write {len(jobs)} tasks to {args.output}")
        # Print first 3 as sample
        for job in jobs[:3]:
            print(f"  {job['id']} | {job['title'][:50]} | {job['block']}")
        if len(jobs) > 3:
            print(f"  ... and {len(jobs) - 3} more")
        return

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {args.output} ({len(jobs)} tasks)")


if __name__ == "__main__":
    main()
