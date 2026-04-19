#!/usr/bin/env python3
"""Factory Portal task/status sidecar.

Serves live reads for /tasks.json and /status/*.json and accepts PUT writes for
the same paths. The data root is configurable so Caddy can serve the React
build from dist/ while this sidecar exposes mutable JSON from the project root.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Config API module (Hermes agent config management)
try:
    import config_api
    CONFIG_API_AVAILABLE = True
except ImportError:
    CONFIG_API_AVAILABLE = False

HOST = os.environ.get("GSD_HOST", "127.0.0.1")
PORT = int(os.environ.get("GSD_PORT", 41935))
DATA_ROOT = Path(os.environ.get("GSD_DATA_ROOT", Path(__file__).resolve().parent)).resolve()
GSD_AUTH_SECRET = os.environ.get("GSD_AUTH_SECRET")
ALLOWED_WRITE_PATHS = {"tasks.json", "jobs.json"}
ALLOWED_WRITE_DIRS = {"status"}


class PortalDataHandler(SimpleHTTPRequestHandler):
    """Serve JSON files from DATA_ROOT and allow controlled PUT writes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DATA_ROOT), **kwargs)

    def _check_auth(self) -> bool:
        if not GSD_AUTH_SECRET:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {GSD_AUTH_SECRET}":
            return True
        self.send_error(401, "Unauthorized")
        return False

    def _is_api_request(self) -> bool:
        return self.path.startswith("/api/config")

    def _handle_api_request(self, method: str) -> None:
        """Route /api/config/* to the config API module."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        status, response = config_api.handle_request(method, self.path, body)
        payload = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        if CONFIG_API_AVAILABLE and self._is_api_request():
            self._handle_api_request("GET")
            return
        if self.path.startswith("/analytics/"):
            self._handle_analytics_summary()
            return
        if self.path.startswith("/budget/"):
            self._handle_budget_status()
            return
        super().do_GET()

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        if CONFIG_API_AVAILABLE and self._is_api_request():
            self._handle_api_request("PATCH")
            return
        self.send_error(405, "PATCH not supported for this path")

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        if CONFIG_API_AVAILABLE and self._is_api_request():
            self._handle_api_request("POST")
            return
        self.send_error(405, "POST not supported for this path")

    def do_PUT(self) -> None:  # noqa: N802 - stdlib hook name
        if not self._check_auth():
            return
        try:
            self._handle_put()
        except Exception as error:  # pragma: no cover - defensive logging
            print(f"PUT error: {error}", file=sys.stderr)
            try:
                self.send_error(500, str(error))
            except Exception:
                pass

    def _handle_put(self) -> None:
        request_path = self.path.lstrip("/")
        if not self._is_allowed_write_path(request_path):
            self.send_error(403, f"Write not allowed: {request_path}")
            return

        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_error(400, "Empty body")
            return
        if length > 1_000_000:
            self.send_error(413, "Payload too large")
            return

        body = self.rfile.read(length)
        try:
            json.loads(body)
        except (json.JSONDecodeError, ValueError) as error:
            self.send_error(400, f"Invalid JSON: {error}")
            return

        file_path = (DATA_ROOT / request_path).resolve()
        if not file_path.is_relative_to(DATA_ROOT):
            self.send_error(403, "Path traversal denied")
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _handle_analytics_summary(self) -> None:
        """Aggregate stats from jobs.json and hermes sessions for /analytics/summary."""
        import urllib.parse
        from datetime import datetime, timedelta, timezone

        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        days = int(params.get("days", ["14"])[0])

        today = datetime.now(timezone.utc).date()
        labels = [(today - timedelta(days=days - 1 - i)).strftime("%b %d") for i in range(days)]

        # --- Tasks by assignee (from jobs.json snapshot) ---
        jobs_path = DATA_ROOT / "jobs.json"
        tasks_by_assignee: list[dict] = []
        task_counts: dict[str, int] = {}
        status_snapshot: dict[str, int] = {"todo": 0, "in_progress": 0, "done": 0, "blocked": 0}
        if jobs_path.exists():
            try:
                data = json.loads(jobs_path.read_bytes())
                tasks = data.get("tasks", [])
                for t in tasks:
                    assignee = t.get("assignee", "unknown")
                    task_counts[assignee] = task_counts.get(assignee, 0) + 1
                    status = t.get("status", "pending")
                    if status == "pending":
                        status_snapshot["todo"] += 1
                    elif status == "done":
                        status_snapshot["done"] += 1
                    elif status == "deferred":
                        status_snapshot["blocked"] += 1
            except (json.JSONDecodeError, KeyError):
                pass
        for assignee, count in sorted(task_counts.items()):
            tasks_by_assignee.append({"label": assignee, "value": count})

        # --- Tasks by status (flat snapshot repeated across all days) ---
        tasks_by_status = [
            {
                "label": label,
                "todo": status_snapshot["todo"],
                "in_progress": status_snapshot["in_progress"],
                "done": status_snapshot["done"],
                "blocked": status_snapshot["blocked"],
            }
            for label in labels
        ]

        # --- Run activity (from ~/.hermes/sessions/*.jsonl) ---
        sessions_dir = Path.home() / ".hermes" / "sessions"
        day_counts: dict[str, dict[str, int]] = {
            label: {"succeeded": 0, "failed": 0, "other": 0} for label in labels
        }
        label_by_date = {
            (today - timedelta(days=days - 1 - i)).isoformat(): labels[i] for i in range(days)
        }
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.jsonl"):
                try:
                    lines = session_file.read_text().splitlines()
                    if not lines:
                        continue
                    meta = json.loads(lines[0])
                    ts = meta.get("timestamp", "")
                    date_str = ts[:10] if ts else ""
                    label = label_by_date.get(date_str)
                    if label:
                        # Check last line for error signal
                        last = json.loads(lines[-1]) if len(lines) > 1 else meta
                        if last.get("role") == "error" or "error" in str(last.get("content", "")).lower():
                            day_counts[label]["failed"] += 1
                        else:
                            day_counts[label]["succeeded"] += 1
                except (json.JSONDecodeError, OSError):
                    pass

        run_activity = [
            {"label": label, **day_counts[label]} for label in labels
        ]

        result = {
            "run_activity": run_activity,
            "tasks_by_status": tasks_by_status,
            "tasks_by_assignee": tasks_by_assignee,
            "approval_rate": {"approved": 0, "rejected": 0, "timed_out": 0},
        }
        payload = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_budget_status(self) -> None:
        """Return per-agent budget status from budget_config.json and status/*.json."""
        budget_cfg_path = DATA_ROOT / "budget_config.json"
        limits: dict[str, float] = {}
        if budget_cfg_path.exists():
            try:
                limits = json.loads(budget_cfg_path.read_bytes()).get("monthly_limits_usd", {})
            except (json.JSONDecodeError, KeyError):
                pass

        agents = []
        for agent_id, limit_usd in limits.items():
            # Try to read runtime state from status/<agent_id>.json
            spent_cents = 0
            runtime_state = None
            status_path = DATA_ROOT / "status" / f"{agent_id}.json"
            if status_path.exists():
                try:
                    st = json.loads(status_path.read_bytes())
                    spent_cents = st.get("total_cost_cents", 0)
                    runtime_state = st
                except (json.JSONDecodeError, KeyError):
                    pass

            spent_usd = spent_cents / 100.0
            pct = spent_usd / limit_usd if limit_usd > 0 else 0.0
            if pct >= 1.0:
                status = {"kind": "paused", "reason": "monthly limit reached"}
            elif pct >= 0.8:
                status = {"kind": "warning", "pct": round(pct * 100, 1)}
            else:
                status = {"kind": "normal"}

            agents.append({
                "agent_id": agent_id,
                "monthly_limit_usd": limit_usd,
                "spent_this_month_usd": round(spent_usd, 4),
                "status": status,
                "incidents": [],
                "runtime_state": runtime_state,
            })

        payload = json.dumps({"agents": agents}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def end_headers(self) -> None:
        path = getattr(self, "path", "") or ""
        if path.endswith(".json"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        try:
            if len(args) >= 2:
                request = str(args[0])
                status = str(args[1])
                if "PUT" in request or not status.startswith("2"):
                    super().log_message(format, *args)
            else:
                super().log_message(format, *args)
        except (AttributeError, TypeError, ValueError):
            super().log_message(format, *args)

    @staticmethod
    def _is_allowed_write_path(request_path: str) -> bool:
        if request_path in ALLOWED_WRITE_PATHS:
            return True

        parts = request_path.split("/")
        return (
            len(parts) == 2
            and parts[0] in ALLOWED_WRITE_DIRS
            and parts[1].endswith(".json")
            and ".." not in request_path
        )


def main() -> None:
    os.chdir(DATA_ROOT)
    server = HTTPServer((HOST, PORT), PortalDataHandler)
    print(f"Factory Portal sidecar -> http://{HOST}:{PORT}/")
    print(f"  Serving: {DATA_ROOT}")
    print("  Writable: tasks.json, jobs.json, status/*.json")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
        server.server_close()


if __name__ == "__main__":
    main()
