#!/usr/bin/env python3
"""Hermes agent config reader/writer for the Factory Portal.

Reads ~/.hermes/profiles/{agent}/config.yaml, redacts secrets,
accepts safe partial updates, and checks inference server health.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

import yaml

HERMES_HOME = Path.home() / ".hermes" / "profiles"
HERMES_ROOT = Path.home() / ".hermes"
STATE_DB = HERMES_ROOT / "state.db"
CRON_JOBS_FILE = HERMES_ROOT / "cron" / "jobs.json"
TINKER_DIR = HERMES_ROOT / "hermes-agent" / "tinker-atropos"

# Agents with Hermes config files
AGENTS = {
    "boot": {
        "label": "Boot",
        "profile_dir": HERMES_HOME / "boot",
        "launchd_label": "com.bootindustries.hermes-boot",
    },
    "kelk": {
        "label": "Kelk",
        "profile_dir": HERMES_HOME / "kelk",
        "launchd_label": "com.bootindustries.hermes-kelk",
    },
    "ig88": {
        "label": "IG-88",
        "profile_dir": HERMES_HOME / "ig88",
        "launchd_label": "com.bootindustries.hermes-ig88",
    },
}

# Fields that contain secrets — values replaced with "***" in GET responses
SECRET_PATTERNS = [
    re.compile(r"api_key", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"recovery_key", re.IGNORECASE),
]

# Fields safe to PATCH (top-level YAML paths)
SAFE_PATCH_FIELDS = {
    "display.compact": bool,
    "display.streaming": bool,
    "display.show_cost": bool,
    "display.show_reasoning": bool,
    "display.skin": str,
    "agent.max_turns": int,
    "agent.tool_use_enforcement": str,
    "approvals.mode": str,
    "max_tokens": int,
    "model.default": str,
    "model.provider": str,
    "model.base_url": str,
    "model.context_length": int,
    "memory.memory_enabled": bool,
    "memory.user_profile_enabled": bool,
    "terminal.cwd": str,
    "terminal.timeout": int,
    "auxiliary.compression.threshold": (int, float),
    "auxiliary.vision.provider": str,
    "auxiliary.vision.model": str,
    "auxiliary.web_extract.provider": str,
    "auxiliary.web_extract.model": str,
    "auxiliary.compression.provider": str,
    "auxiliary.compression.model": str,
    "auxiliary.compression.summary_provider": str,
    "auxiliary.compression.summary_model": str,
    "auxiliary.session_search.provider": str,
    "auxiliary.session_search.model": str,
    "auxiliary.skills_hub.provider": str,
    "auxiliary.skills_hub.model": str,
    "auxiliary.approval.provider": str,
    "auxiliary.approval.model": str,
    "auxiliary.mcp.provider": str,
    "auxiliary.mcp.model": str,
    "auxiliary.flush_memories.provider": str,
    "auxiliary.flush_memories.model": str,
    "toolsets": list,
}

# Valid values for enum-like fields
FIELD_VALIDATORS = {
    "agent.tool_use_enforcement": {"none", "warn", "enforce"},
    "approvals.mode": {"off", "per_tool", "always"},
    "model.provider": {"custom", "nous", "openrouter", "anthropic", "openai",
                        "mlx-vlm:41961", "mlx-vlm:41962", "flash-moe:41966"},
}


def _config_path(agent: str) -> Path:
    info = AGENTS.get(agent)
    if not info:
        raise KeyError(f"Unknown agent: {agent}")
    return info["profile_dir"] / "config.yaml"


def _redact_secrets(data: Any, path: str = "") -> Any:
    """Recursively redact values whose key matches secret patterns."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            full_path = f"{path}.{key}" if path else key
            # max_tokens is a legitimate config field, not a secret
            if key != "max_tokens" and any(p.search(key) for p in SECRET_PATTERNS):
                result[key] = "***" if isinstance(value, str) else None
            else:
                result[key] = _redact_secrets(value, full_path)
        return result
    if isinstance(data, list):
        return [_redact_secrets(item, f"{path}[{i}]") for i, item in enumerate(data)]
    return data


def _get_nested(data: dict, dotted_key: str) -> Any:
    """Get a nested value by dotted path (e.g. 'display.compact')."""
    keys = dotted_key.split(".")
    current = data
    for k in keys:
        if not isinstance(current, dict) or k not in current:
            return None
        current = current[k]
    return current


def _set_nested(data: dict, dotted_key: str, value: Any) -> None:
    """Set a nested value by dotted path, creating intermediate dicts."""
    keys = dotted_key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value


def read_config(agent: str) -> dict:
    """Read and parse an agent's config.yaml. Returns redacted copy."""
    path = _config_path(agent)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    return raw or {}


def _derive_provider(config: dict, dotted_prefix: str = "model") -> str:
    """Derive the actual inference provider from config.

    Checks base_url for local engine:port mapping FIRST,
    then cloud providers by host, then falls back to stored provider.
    The dotted_prefix param allows re-use for auxiliary.* slots.
    """
    base_url = _get_nested(config, f"{dotted_prefix}.base_url") or ""
    model_path = _get_nested(config, f"{dotted_prefix}.default") or ""
    # For aux slots, model path might be under 'model' key directly
    if not model_path and dotted_prefix != "model":
        model_path = _get_nested(config, f"{dotted_prefix}.model") or ""
    stored = _get_nested(config, f"{dotted_prefix}.provider") or "unknown"

    # Local engines: identify by base_url port FIRST (never trust stored provider)
    if "127.0.0.1" in base_url or "localhost" in base_url:
        port = base_url.split(":")[-1].split("/")[0]
        # 26B flash-moe on any port
        if "26b" in model_path.lower() or "flash-moe" in model_path.lower():
            return f"flash-moe:{port}"
        return f"mlx-vlm:{port}"

    # Cloud providers by host
    if "nousresearch" in base_url:
        return "nous"
    if "openrouter" in base_url:
        return "openrouter"
    if "anthropic" in base_url:
        return "anthropic"
    if "openai" in base_url:
        return "openai"

    # Legacy "custom" — can't determine from config alone
    if stored == "custom":
        return stored

    return stored


def read_config_safe(agent: str) -> dict:
    """Read config with secrets redacted for API responses."""
    raw = read_config(agent)
    return _redact_secrets(raw)


def validate_patch(agent: str, patch: dict[str, Any]) -> list[str]:
    """Validate a patch dict. Returns list of error strings (empty = valid)."""
    errors = []
    for key, value in patch.items():
        if key not in SAFE_PATCH_FIELDS:
            errors.append(f"Field '{key}' is not patchable")
            continue
        expected_type = SAFE_PATCH_FIELDS[key]
        # Allow null for optional fields (treat as removing the field)
        if value is None:
            # null is valid for all fields — it removes the setting
            continue
        # Handle tuple of types (e.g., (int, float) for threshold)
        if isinstance(expected_type, tuple):
            if not isinstance(value, expected_type):
                type_names = " or ".join(t.__name__ for t in expected_type)
                errors.append(f"Field '{key}' expects {type_names}, got {type(value).__name__}")
                continue
        elif not isinstance(value, expected_type):
            errors.append(f"Field '{key}' expects {expected_type.__name__}, got {type(value).__name__}")
            continue
        if key in FIELD_VALIDATORS:
            valid = FIELD_VALIDATORS[key]
            if value not in valid:
                errors.append(f"Field '{key}' must be one of: {', '.join(sorted(valid))}")
    return errors


def apply_patch(agent: str, patch: dict[str, Any]) -> dict:
    """Apply a validated patch to an agent's config.yaml. Returns new config.

    Reads current config, applies changes, writes back, returns the new config.
    Does NOT redact — returns full config for verification.
    """
    path = _config_path(agent)
    raw = read_config(agent)

    for key, value in patch.items():
        _set_nested(raw, key, value)

    # Write back preserving order as much as possible
    with open(path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return raw


def _get_inference_url(config: dict) -> str | None:
    """Extract the inference URL from config, handling both local and cloud providers."""
    # Direct base_url (local providers)
    base_url = _get_nested(config, "model.base_url")
    if base_url:
        return base_url
    # Check custom_providers for the matching provider
    provider = _get_nested(config, "model.provider")
    providers_list = _get_nested(config, "custom_providers") or []
    for cp in providers_list:
        if cp.get("name", "").lower().replace(" ", "-") == provider or cp.get("base_url"):
            url = cp.get("base_url")
            if url:
                return url
    # Check providers section
    providers_dict = _get_nested(config, "providers") or {}
    for name, p in providers_dict.items():
        api = p.get("api")
        if api:
            return api
    return None


def check_inference_health(agent: str) -> dict:
    """Check if an agent's inference server is reachable.

    Returns { "reachable": bool, "url": str, "status": int|None, "error": str|None }
    """
    config = read_config(agent)
    url = _get_inference_url(config)
    provider = _get_nested(config, "model.provider") or "unknown"

    if not url:
        # Cloud providers without local URL are considered "external"
        if provider in ("nous", "openrouter", "anthropic", "openai"):
            return {"reachable": True, "url": f"cloud:{provider}", "status": 200, "error": None}
        return {"reachable": False, "url": None, "status": None, "error": "No inference URL configured"}

    # For cloud providers, just check connectivity to the host
    if not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return {"reachable": True, "url": url, "status": 200, "error": None}

    health_url = f"{url.rstrip('/')}/models"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"reachable": True, "url": health_url, "status": resp.status, "error": None}
    except urllib.error.URLError as e:
        return {"reachable": False, "url": health_url, "status": None, "error": str(e)}
    except Exception as e:
        return {"reachable": False, "url": health_url, "status": None, "error": str(e)}


def check_all_health() -> dict:
    """Check inference health for all agents."""
    return {agent: check_inference_health(agent) for agent in AGENTS}


def restart_gateway(agent: str) -> dict:
    """Restart an agent's Hermes gateway via launchctl."""
    info = AGENTS.get(agent)
    if not info:
        return {"ok": False, "error": f"Unknown agent: {agent}"}

    label = info["launchd_label"]
    try:
        # Stop then start
        subprocess.run(["launchctl", "stop", label], capture_output=True, timeout=10)
        subprocess.run(["launchctl", "start", label], capture_output=True, timeout=10)
        return {"ok": True, "agent": agent, "label": label}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "launchctl timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Phase 3: Memory Budget & Restart Gate ---

# Estimated RSS (GB) per model when loaded into memory
MODEL_MEMORY_GB = {
    "mlx-community/gemma-4-e4b-it-6bit": 7.3,
    "gemma-4-e4b-it-6bit": 7.3,
    "gemma-4-26b-a4b-it-6bit": 3.0,
    "mlx-community/gemma-4-26b-a4b-it-6bit": 3.0,
}

# Ports and their associated plists (for restart sequencing)
INFERENCE_PORTS = {
    "mlx-vlm:41961": {"port": 41961, "plist": "com.bootindustries.mlx-vlm-boot"},
    "mlx-vlm:41962": {"port": 41962, "plist": "com.bootindustries.mlx-vlm-kelk"},
    "flash-moe:41966": {"port": 41966, "plist": "com.bootindustries.flash-moe-26b"},
}

import time

# Guard: prevent concurrent restarts (timestamp-based)
_restart_lock = {"busy": False, "last_ts": 0}


def check_memory_budget() -> dict:
    """Check live memory usage of inference servers.

    Returns {"total_gb": float, "used_by_inference_gb": float, "free_gb": float,
             "models": [{"provider": str, "port": int, "model": str, "loaded": bool, "est_gb": float}]}
    """
    # Use macOS sysctl — no psutil dependency needed
    import subprocess as _sp
    total_bytes = int(
        _sp.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
    )
    total_gb = total_bytes / (1024 ** 3)
    # Parse "free" from top output: "PhysMem: 31G used (3G wired, 8G compressor), 493M unused."
    top_out = _sp.run(["top", "-l", "1", "-s", "0"], capture_output=True, text=True).stdout
    import re as _re
    _m = _re.search(r"(\d+[MG])\s*unused", top_out)
    if _m:
        val_str = _m.group(1)
        if val_str.endswith("G"):
            available_gb = float(val_str[:-1])
        else:
            available_gb = float(val_str[:-1]) / 1024
    else:
        available_gb = total_gb * 0.15  # conservative fallback

    models = []
    for agent_id, info in AGENTS.items():
        config = read_config(agent_id)
        provider = _derive_provider(config)
        model = _get_nested(config, "model.default") or ""
        port = None
        if ":" in provider:
            port_str = provider.split(":")[-1].split("/")[0]
            try:
                port = int(port_str)
            except ValueError:
                pass

        # Check if the inference server is actually responding
        loaded = False
        if port:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/v1/models", method="GET"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    loaded = resp.status == 200
            except Exception:
                pass

        # Estimate memory from model name
        est_gb = 0.0
        for mname, mem_est in MODEL_MEMORY_GB.items():
            if mname in model or model in mname:
                est_gb = mem_est
                break

        models.append({
            "agent": agent_id,
            "provider": provider,
            "port": port,
            "model": model,
            "loaded": loaded,
            "est_gb": est_gb,
        })

    used_by_inference_gb = sum(m["est_gb"] for m in models if m["loaded"])

    return {
        "total_gb": round(total_gb, 1),
        "available_gb": round(available_gb, 1),
        "used_by_inference_gb": round(used_by_inference_gb, 1),
        "headroom_gb": round(available_gb - used_by_inference_gb, 1),
        "models": models,
    }


def restart_gateway_safe(agent: str, force: bool = False) -> dict:
    """Restart with memory budget pre-flight check and sequencing.

    Steps:
    1. Check if another restart is in progress (concurrent guard).
    2. Verify the inference server for this agent is reachable (or cloud).
    3. If local engine: check available memory would allow re-loading.
    4. Stop the gateway, wait 2s, start it (don't restart inference server).
    5. Verify the gateway comes back up.
    """
    info = AGENTS.get(agent)
    if not info:
        return {"ok": False, "error": f"Unknown agent: {agent}"}

    label = info["launchd_label"]

    # Guard: concurrent restart prevention (5s cooldown)
    now = time.time()
    if _restart_lock["busy"] and (now - _restart_lock["last_ts"]) < 5:
        return {"ok": False, "error": "Another restart is in progress. Wait a few seconds."}
    _restart_lock["busy"] = True
    _restart_lock["last_ts"] = now

    try:
        config = read_config(agent)
        provider = _derive_provider(config)
        model = _get_nested(config, "model.default") or ""
        inference_url = _get_inference_url(config)

        # Check if local inference server
        is_local = False
        port = None
        if inference_url and ("127.0.0.1" in inference_url or "localhost" in inference_url):
            is_local = True
            port = int(inference_url.split(":")[-1].split("/")[0])

        # Memory pre-flight for local models
        if is_local and not force:
            budget = check_memory_budget()
            # Check if model would need to be re-loaded
            est_gb = 0
            for mname, mem_est in MODEL_MEMORY_GB.items():
                if mname in model:
                    est_gb = mem_est
                    break
            if est_gb > 0 and budget["available_gb"] < est_gb * 0.5:
                return {
                    "ok": False,
                    "error": f"Insufficient memory for {model} (~{est_gb}GB). Only {budget['available_gb']}GB available. Stop other services first.",
                    "budget": budget,
                    "needs_force": True,
                }

        # Verify inference server is up (for local providers)
        if is_local:
            health = check_inference_health(agent)
            if not health["reachable"]:
                return {
                    "ok": False,
                    "error": f"Inference server on :{port} is not reachable. Cannot restart gateway without a live model.",
                    "inference_health": health,
                }

        # Execute restart
        subprocess.run(["launchctl", "stop", label], capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run(["launchctl", "start", label], capture_output=True, timeout=10)

        # Verify gateway comes back (15s timeout)
        time.sleep(3)
        running = False
        try:
            result = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True, text=True, timeout=5,
            )
            running = '"PID"' in result.stdout
        except Exception:
            pass

        return {
            "ok": True,
            "agent": agent,
            "label": label,
            "provider": provider,
            "gateway_running": running,
            "inference_url": inference_url,
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "launchctl timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        _restart_lock["busy"] = False


def get_agent_summaries() -> list[dict]:
    """Return summary info for all agents (for the config page overview)."""
    summaries = []
    for agent_id, info in AGENTS.items():
        try:
            config = read_config(agent_id)
            summary = {
                "id": agent_id,
                "label": info["label"],
                "model": _get_nested(config, "model.default") or "—",
                "provider": _derive_provider(config),
                "base_url": _get_nested(config, "model.base_url") or "—",
                "display": {
                    "compact": _get_nested(config, "display.compact"),
                    "streaming": _get_nested(config, "display.streaming"),
                    "show_cost": _get_nested(config, "display.show_cost"),
                    "show_reasoning": _get_nested(config, "display.show_reasoning"),
                    "skin": _get_nested(config, "display.skin"),
                },
                "max_turns": _get_nested(config, "agent.max_turns"),
                "max_tokens": _get_nested(config, "max_tokens"),
                "tool_use_enforcement": _get_nested(config, "agent.tool_use_enforcement"),
                "approval_mode": _get_nested(config, "approvals.mode"),
                "toolsets": _get_nested(config, "toolsets") or [],
                "memory": {
                    "memory_enabled": _get_nested(config, "memory.memory_enabled"),
                    "user_profile_enabled": _get_nested(config, "memory.user_profile_enabled"),
                },
                "terminal": {
                    "cwd": _get_nested(config, "terminal.cwd"),
                    "timeout": _get_nested(config, "terminal.timeout"),
                },
                "compression_threshold": _get_nested(config, "auxiliary.compression.threshold"),
                "mcp_servers": _get_nested(config, "mcp_servers") or {},
            }
        except Exception as e:
            summary = {
                "id": agent_id,
                "label": info["label"],
                "error": str(e),
            }
        summaries.append(summary)
    return summaries


def _query_sessions(limit: int = 20) -> list[dict]:
    """Query Hermes state.db for recent sessions."""
    if not STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT id, source, user_id, model, started_at, ended_at,
                      message_count, tool_call_count, input_tokens, output_tokens,
                      title
               FROM sessions ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        for row in rows:
            for key in ("started_at", "ended_at"):
                if row.get(key):
                    from datetime import datetime, timezone
                    row[key] = datetime.fromtimestamp(
                        row[key], tz=timezone.utc
                    ).isoformat()
        return rows
    except Exception:
        return []


def _query_session_messages(session_id: str, limit: int = 30) -> list[dict]:
    """Query recent messages for a session, focusing on tool calls."""
    if not STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT id, role, tool_calls, tool_name, timestamp,
                      substr(content, 1, 120) as preview
               FROM messages
               WHERE session_id = ? AND (tool_calls IS NOT NULL OR role = 'assistant')
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        for row in rows:
            if row.get("tool_calls"):
                try:
                    parsed = json.loads(row["tool_calls"])
                    row["tool_names"] = [
                        t.get("function", {}).get("name", "?") for t in parsed
                    ]
                except Exception:
                    row["tool_names"] = []
            else:
                row["tool_names"] = []
            if row.get("timestamp"):
                from datetime import datetime, timezone
                row["timestamp"] = datetime.fromtimestamp(
                    row["timestamp"], tz=timezone.utc
                ).isoformat()
        return rows
    except Exception:
        return []


def get_hermes_sessions() -> dict:
    """Get sessions and recent tool call activity."""
    sessions = _query_sessions(20)
    active = [s for s in sessions if not s.get("ended_at")]
    completed = [s for s in sessions if s.get("ended_at")]
    tool_distribution: dict[str, int] = {}
    if STATE_DB.exists():
        try:
            conn = sqlite3.connect(str(STATE_DB))
            cur = conn.execute(
                """SELECT tool_calls FROM messages
                   WHERE tool_calls IS NOT NULL ORDER BY timestamp DESC LIMIT 200"""
            )
            for (tc_str,) in cur.fetchall():
                try:
                    parsed = json.loads(tc_str)
                    for t in parsed:
                        name = t.get("function", {}).get("name", "?")
                        tool_distribution[name] = tool_distribution.get(name, 0) + 1
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass
    return {
        "active": active,
        "completed": completed,
        "total": len(sessions),
        "tool_distribution": dict(
            sorted(tool_distribution.items(), key=lambda x: -x[1])[:15]
        ),
    }


def get_session_detail(session_id: str) -> dict:
    """Get session detail with recent tool call messages."""
    if not STATE_DB.exists():
        return {"error": "state.db not found"}
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT id, source, user_id, model, started_at, ended_at,
                      message_count, tool_call_count, input_tokens, output_tokens,
                      title, estimated_cost_usd, cost_status
               FROM sessions WHERE id = ?""",
            (session_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Session {session_id} not found"}
        session = dict(row)
        for key in ("started_at", "ended_at"):
            if session.get(key):
                from datetime import datetime, timezone
                session[key] = datetime.fromtimestamp(
                    session[key], tz=timezone.utc
                ).isoformat()
        session["recent_messages"] = _query_session_messages(session_id, 30)
        return session
    except Exception as e:
        return {"error": str(e)}


def get_cron_jobs() -> dict:
    """Read cron jobs from jobs.json."""
    if not CRON_JOBS_FILE.exists():
        return {"jobs": [], "count": 0}
    try:
        with open(CRON_JOBS_FILE) as f:
            jobs = json.load(f)
        if not isinstance(jobs, list):
            jobs = []
        for job in jobs:
            schedule = job.get("schedule", {})
            job["schedule_display"] = (
                schedule.get("display")
                or schedule.get("value")
                or str(schedule)
            )
            job["state"] = (
                "paused"
                if not job.get("enabled", True)
                else job.get("state", "scheduled")
            )
        return {"jobs": jobs, "count": len(jobs)}
    except Exception as e:
        return {"jobs": [], "count": 0, "error": str(e)}


def get_rl_runs() -> dict:
    """Check RL training configuration and list any runs."""
    env = os.environ.copy()
    has_tinker = bool(env.get("TINKER_API_KEY"))
    has_wandb = bool(env.get("WANDB_API_KEY"))
    tinker_exists = TINKER_DIR.exists()
    configured = has_tinker and has_wandb and tinker_exists

    runs = []
    if tinker_exists:
        runs_dir = TINKER_DIR / "runs"
        if runs_dir.exists():
            for run_dir in sorted(runs_dir.iterdir(), reverse=True):
                if run_dir.is_dir():
                    run_info = {"id": run_dir.name, "path": str(run_dir)}
                    config_file = run_dir / "config.yaml"
                    if config_file.exists():
                        try:
                            import yaml
                            with open(config_file) as f:
                                run_info["config"] = yaml.safe_load(f) or {}
                        except Exception:
                            pass
                    runs.append(run_info)

    return {
        "configured": configured,
        "has_tinker_key": has_tinker,
        "has_wandb_key": has_wandb,
        "tinker_atropos_exists": tinker_exists,
        "runs": runs[:10],
        "run_count": len(runs),
    }


def handle_request(method: str, path: str, body: bytes | None = None) -> tuple[int, dict]:
    """Route handler for /api/config/* requests.

    Returns (status_code, response_dict).
    """
    # Parse path: /api/config/{agent} or /api/config/{agent}/health or /api/config/{agent}/restart
    parts = path.strip("/").split("/")
    # Expected: ["api", "config", agent] or ["api", "config", agent, action]

    if len(parts) < 3:
        # GET /api/config — list all agents
        if method == "GET":
            return 200, {"agents": get_agent_summaries()}
        return 405, {"error": "Method not allowed"}

    agent = parts[2]

    # Non-agent routes — must be checked before AGENTS validation
    if agent == "memory-budget" and method == "GET":
        return 200, check_memory_budget()

    if agent == "sessions" and method == "GET":
        if len(parts) > 3:
            # GET /api/config/sessions/{session_id}
            return 200, get_session_detail(parts[3])
        return 200, get_hermes_sessions()

    if agent == "cron-jobs" and method == "GET":
        return 200, get_cron_jobs()

    if agent == "rl-runs" and method == "GET":
        return 200, get_rl_runs()

    if agent not in AGENTS:
        return 404, {"error": f"Unknown agent: {agent}"}

    action = parts[3] if len(parts) > 3 else None

    # GET /api/config/{agent}/health
    if action == "health" and method == "GET":
        return 200, check_inference_health(agent)

    # POST /api/config/{agent}/restart
    if action == "restart" and method == "POST":
        force = False
        if body:
            try:
                body_data = json.loads(body)
                force = body_data.get("force", False)
            except Exception:
                pass
        result = restart_gateway_safe(agent, force=force)
        return 200 if result["ok"] else 500, result

    # POST /api/config/{agent}/mcp/{server_name}/toggle
    if action == "mcp" and method == "POST" and len(parts) >= 6 and parts[5] == "toggle":
        server_name = parts[4]
        try:
            body_data = json.loads(body or b"{}")
            enabled = body_data.get("enabled")
            if enabled is None or not isinstance(enabled, bool):
                return 400, {"error": "Body must include 'enabled' (bool)"}
            path_key = f"mcp_servers.{server_name}.enabled"
            # Directly modify the YAML since mcp_servers isn't in SAFE_PATCH_FIELDS
            config = read_config(agent)
            mcp = config.get("mcp_servers", {})
            if server_name not in mcp:
                return 404, {"error": f"MCP server '{server_name}' not found"}
            mcp[server_name]["enabled"] = enabled
            config_path = _config_path(agent)
            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return 200, {"ok": True, "agent": agent, "server": server_name, "enabled": enabled}
        except Exception as e:
            return 500, {"error": str(e)}

    # GET /api/config/{agent}
    if action is None and method == "GET":
        try:
            config = read_config_safe(agent)
            health = check_inference_health(agent)
            return 200, {"agent": agent, "config": config, "health": health}
        except FileNotFoundError as e:
            return 404, {"error": str(e)}

    # PATCH /api/config/{agent}
    if action is None and method == "PATCH":
        try:
            patch_data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return 400, {"error": "Invalid JSON body"}

        if not isinstance(patch_data, dict):
            return 400, {"error": "Body must be a JSON object"}

        errors = validate_patch(agent, patch_data)
        if errors:
            return 422, {"errors": errors}

        try:
            new_config = apply_patch(agent, patch_data)
            return 200, {
                "ok": True,
                "agent": agent,
                "updated_fields": list(patch_data.keys()),
                "config": _redact_secrets(new_config),
            }
        except Exception as e:
            return 500, {"error": str(e)}

    return 404, {"error": "Not found"}
