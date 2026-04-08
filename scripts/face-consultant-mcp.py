#!/usr/bin/env python3
"""
face-consultant-mcp.py — MCP stdio consultant server for IG-88 face ensemble.

Purpose
-------
First deliberative face for IG-88's ensemble-agent architecture per FCT056.
This is an MCP (Model Context Protocol) stdio server that exposes ONE tool
to the reflex face: `consult_deliberative(query, context?, max_tokens?)`.

The tool proxies a single-shot completion to an OpenAI-compatible endpoint
specified entirely via environment variables, so the same script can host
any future face (analyst, fast, vision, ...) by being launched with a
different env block. See FCT056 §4 (option A, MCP-server-as-consultant)
and §5 (initial IG-88 ensemble).

Invocation
----------
Invoked by Hermes via a `mcp_servers:` entry in the profile config
(`~/.hermes/profiles/ig88/config.yaml`). Hermes spawns this as a child
process, speaks JSON-RPC 2.0 over stdio, and routes stdout/stdin to the
agent runtime. All operational logs go to stderr so they never contaminate
the protocol channel.

Example profile snippet:

    mcp_servers:
      consultants:
        command: python3
        args:
          - /Users/nesbitt/dev/factory/scripts/face-consultant-mcp.py
        env:
          FACE_NAME: deliberative
          FACE_MODEL: google/gemma-4-31b-it
          FACE_PROVIDER: openrouter
          FACE_BASE_URL: https://openrouter.ai/api/v1
          FACE_API_KEY_ENV: OPENROUTER_API_KEY
          FACE_BUDGET_USD_DAILY: "1.00"
        tools:
          include: [consult_deliberative]

Environment variables
---------------------
  FACE_NAME                    Display name for this face (default "deliberative")
  FACE_MODEL                   REQUIRED. Model id to send to the backend.
  FACE_PROVIDER                Display-only provider name (default "openrouter")
  FACE_BASE_URL                OpenAI-compatible base URL
                               (default "https://openrouter.ai/api/v1")
  FACE_API_KEY_ENV             NAME of the env var holding the API key —
                               the key itself never appears in argv/config.
                               (default "OPENROUTER_API_KEY")
  FACE_BUDGET_USD_DAILY        Daily consult budget ceiling (default "1.00")
  FACE_COST_PER_1K_INPUT_USD   Estimated cost (default "0.0005")
  FACE_COST_PER_1K_OUTPUT_USD  Estimated cost (default "0.0015")
  FACE_MAX_TOKENS_DEFAULT      Default max_tokens for completions (default "1024")
  FACE_TIMEOUT_SECONDS         HTTP request timeout (default "60")
  HERMES_HOME                  Profile dir; budget/log files live here
                               (default "~/.hermes/profiles/ig88")

Security posture
----------------
- Refuses ALL `sampling/createMessage` (and any `sampling/*`) requests with
  JSON-RPC -32601 Method not found. This is the FCT056 §8 #5 requirement:
  MCP sampling is bidirectional, and an untrusted upstream could otherwise
  use this server as a pivot to burn the deliberative budget by requesting
  completions from IG-88's own model.
- Enforces a per-profile daily USD budget ceiling. Budget exceeded returns
  a tool error; no API call is made.
- The actual API key is read at tool-call time via os.environ[FACE_API_KEY_ENV];
  this script never stores, logs, or serializes it.

Design context
--------------
See /Users/nesbitt/dev/factory/docs/fct/FCT056 Ensemble Agents and Face-Based
Cognition — Architecture Proposal.md, especially §4, §5, §6, §8.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# MCP protocol constants
# ---------------------------------------------------------------------------
#
# Per the MCP spec, servers and clients negotiate protocolVersion during
# initialize. We advertise a recent stable version string; Hermes's client
# echoes its own, and we accept whatever the client sends.
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "face-consultant-mcp"
SERVER_VERSION = "0.1.0"

# JSON-RPC 2.0 error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Config loaded from env at startup
# ---------------------------------------------------------------------------
class Config:
    """Immutable view of the FACE_* env config for this server instance."""

    def __init__(self) -> None:
        self.face_name: str = os.environ.get("FACE_NAME", "deliberative").strip() or "deliberative"
        self.face_model: str = os.environ.get("FACE_MODEL", "").strip()
        self.face_provider: str = os.environ.get("FACE_PROVIDER", "openrouter").strip() or "openrouter"
        self.face_base_url: str = (
            os.environ.get("FACE_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
            or "https://openrouter.ai/api/v1"
        )
        self.face_api_key_env: str = (
            os.environ.get("FACE_API_KEY_ENV", "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
        )
        self.budget_usd_daily: float = _f(os.environ.get("FACE_BUDGET_USD_DAILY"), 1.00)
        self.cost_per_1k_input: float = _f(os.environ.get("FACE_COST_PER_1K_INPUT_USD"), 0.0005)
        self.cost_per_1k_output: float = _f(os.environ.get("FACE_COST_PER_1K_OUTPUT_USD"), 0.0015)
        self.max_tokens_default: int = int(_f(os.environ.get("FACE_MAX_TOKENS_DEFAULT"), 1024))
        self.timeout_seconds: float = _f(os.environ.get("FACE_TIMEOUT_SECONDS"), 60.0)

        hermes_home = os.environ.get("HERMES_HOME", "").strip()
        if hermes_home:
            self.profile_dir = pathlib.Path(hermes_home).expanduser()
        else:
            self.profile_dir = pathlib.Path("~/.hermes/profiles/ig88").expanduser()

        self.budget_path = self.profile_dir / "consult-budget.json"
        self.log_path = self.profile_dir / "consult-log.jsonl"

    @property
    def tool_name(self) -> str:
        # TODO: make tool name fully parametric (consult_{face_name}) once a
        # second face lands. For Phase 2 per FCT056 §7 we hardcode
        # consult_deliberative so the soul-file guidance in §6 can reference
        # a stable symbol. The log output still uses FACE_NAME for clarity.
        return "consult_deliberative"


def _f(raw: str | None, default: float) -> float:
    if raw is None or raw.strip() == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


# ---------------------------------------------------------------------------
# Logging (to stderr only — stdout is the JSON-RPC channel)
# ---------------------------------------------------------------------------
def _log(level: str, component: str, message: str) -> None:
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print(f"[{ts}] [{level}] [{component}] {message}", file=sys.stderr, flush=True)


def log_info(component: str, message: str) -> None:
    _log("info", component, message)


def log_warn(component: str, message: str) -> None:
    _log("warn", component, message)


def log_error(component: str, message: str) -> None:
    _log("error", component, message)


# ---------------------------------------------------------------------------
# Budget ledger
# ---------------------------------------------------------------------------
class Budget:
    """File-backed daily consult budget. Single-profile, non-concurrent.

    Format on disk:
        {"date": "YYYY-MM-DD", "spent_usd": 0.0, "calls": 0}

    Rolls over automatically on date change. All access is synchronous and
    happens under the stdio reader's single thread — no locking needed for
    the IG-88 profile use case (one MCP server process per profile).
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cfg.profile_dir.mkdir(parents=True, exist_ok=True)

    def _today(self) -> str:
        return _dt.date.today().isoformat()

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.cfg.budget_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("budget file is not an object")
            return data
        except FileNotFoundError:
            return {"date": self._today(), "spent_usd": 0.0, "calls": 0}
        except (json.JSONDecodeError, ValueError) as e:
            log_warn("budget", f"corrupt budget file {self.cfg.budget_path}: {e}; resetting")
            return {"date": self._today(), "spent_usd": 0.0, "calls": 0}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self.cfg.budget_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.cfg.budget_path)

    def snapshot(self) -> tuple[float, int, float]:
        """Return (spent_usd, calls, remaining_usd) for today."""
        data = self._read()
        today = self._today()
        if data.get("date") != today:
            log_info("budget", f"budget rollover: previous={data.get('date')} -> today={today}")
            data = {"date": today, "spent_usd": 0.0, "calls": 0}
            self._write(data)
        spent = float(data.get("spent_usd", 0.0))
        calls = int(data.get("calls", 0))
        remaining = max(0.0, self.cfg.budget_usd_daily - spent)
        return spent, calls, remaining

    def check_available(self) -> tuple[bool, float]:
        """Return (has_budget, remaining_usd)."""
        _spent, _calls, remaining = self.snapshot()
        return remaining > 0.0, remaining

    def charge(self, cost_usd: float) -> tuple[float, int, float]:
        """Record a charge. Returns (new_spent, new_calls, new_remaining)."""
        data = self._read()
        today = self._today()
        if data.get("date") != today:
            data = {"date": today, "spent_usd": 0.0, "calls": 0}
        data["spent_usd"] = float(data.get("spent_usd", 0.0)) + float(cost_usd)
        data["calls"] = int(data.get("calls", 0)) + 1
        self._write(data)
        remaining = max(0.0, self.cfg.budget_usd_daily - data["spent_usd"])
        return data["spent_usd"], data["calls"], remaining


# ---------------------------------------------------------------------------
# Consult log (JSONL)
# ---------------------------------------------------------------------------
def append_consult_log(cfg: Config, record: dict[str, Any]) -> None:
    try:
        cfg.profile_dir.mkdir(parents=True, exist_ok=True)
        with cfg.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log_warn("consult-log", f"failed to append consult log: {e}")


# ---------------------------------------------------------------------------
# HTTP client — stdlib only, OpenAI-compatible chat completions
# ---------------------------------------------------------------------------
class HttpError(Exception):
    def __init__(self, status: int, body_preview: str):
        super().__init__(f"HTTP {status}: {body_preview[:400]}")
        self.status = status
        self.body_preview = body_preview


def call_chat_completions(
    cfg: Config,
    api_key: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    url = f"{cfg.face_base_url}/chat/completions"
    payload = {
        "model": cfg.face_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}",
    }
    # OpenRouter-specific courtesy headers; harmless elsewhere.
    headers["HTTP-Referer"] = "https://github.com/bootindustries/factory"
    headers["X-Title"] = f"factory/{cfg.face_name}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
            if status != 200:
                raise HttpError(status, raw)
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_raw = ""
        try:
            body_raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise HttpError(e.code, body_raw) from e
    except urllib.error.URLError as e:
        raise HttpError(0, f"URLError: {e.reason}") from e
    except TimeoutError as e:
        raise HttpError(0, f"timeout after {cfg.timeout_seconds}s: {e}") from e


# ---------------------------------------------------------------------------
# Tool: consult_deliberative
# ---------------------------------------------------------------------------
TOOL_DESCRIPTION = (
    "Consult the deliberative face — a larger peer model — for a second opinion "
    "on an ambiguous, high-stakes, or regime-shift question. This is a deliberate "
    "reach sideways, not a fallback: use it when the stakes warrant the extra "
    "latency and cost (see FCT056 §6 for when the tide should turn). Returns the "
    "deliberative face's raw response text. Budget-capped per day."
)


def tool_schema(cfg: Config) -> dict[str, Any]:
    return {
        "name": cfg.tool_name,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The distilled question to put to the deliberative face. "
                        "Prefer a self-contained question over pasting raw conversation."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional additional context (market state, user message, "
                        "prior reasoning trace). Will be prepended as a system message."
                    ),
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Response cap; defaults to FACE_MAX_TOKENS_DEFAULT.",
                    "minimum": 1,
                    "maximum": 8192,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def tool_result_text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def handle_consult(cfg: Config, budget: Budget, args: dict[str, Any]) -> dict[str, Any]:
    t0 = time.monotonic()

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return tool_result_text(
            "error: 'query' is required and must be a non-empty string",
            is_error=True,
        )
    context = args.get("context")
    if context is not None and not isinstance(context, str):
        return tool_result_text("error: 'context' must be a string if provided", is_error=True)

    max_tokens_raw = args.get("max_tokens")
    if max_tokens_raw is None:
        max_tokens = cfg.max_tokens_default
    else:
        try:
            max_tokens = int(max_tokens_raw)
        except (TypeError, ValueError):
            return tool_result_text("error: 'max_tokens' must be an integer", is_error=True)
        if max_tokens < 1:
            return tool_result_text("error: 'max_tokens' must be >= 1", is_error=True)

    # Budget check BEFORE any API call
    has_budget, remaining = budget.check_available()
    if not has_budget:
        spent, calls, _ = budget.snapshot()
        msg = (
            f"consult budget exhausted for today: "
            f"spent ${spent:.4f} / ${cfg.budget_usd_daily:.2f} across {calls} calls. "
            f"No API call made. Reflex face must handle this turn, or wait for daily rollover."
        )
        log_warn("budget", msg)
        return tool_result_text(msg, is_error=True)

    # API key resolution
    api_key = os.environ.get(cfg.face_api_key_env, "").strip()
    if not api_key:
        msg = (
            f"API key env var '{cfg.face_api_key_env}' is empty or unset; "
            f"cannot reach {cfg.face_provider}. No API call made."
        )
        log_error("consult", msg)
        return tool_result_text(msg, is_error=True)

    # Build messages
    system_prompt = (
        f"You are the {cfg.face_name} face of IG-88, a peer consultant being "
        f"reached for deliberately. Respond concisely and directly to the query. "
        f"Do not restate the question."
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if context and context.strip():
        messages.append({"role": "system", "content": f"Context:\n{context}"})
    messages.append({"role": "user", "content": query})

    # Call backend
    try:
        response = call_chat_completions(cfg, api_key, messages, max_tokens)
    except HttpError as e:
        msg = (
            f"{cfg.face_provider} call failed: HTTP {e.status}. "
            f"Body preview: {e.body_preview[:300]}"
        )
        log_error("consult", msg)
        return tool_result_text(msg, is_error=True)
    except Exception as e:  # noqa: BLE001 — we must never crash the server
        msg = f"unexpected error calling {cfg.face_provider}: {type(e).__name__}: {e}"
        log_error("consult", msg)
        return tool_result_text(msg, is_error=True)

    # Extract text and usage
    try:
        choices = response.get("choices") or []
        if not choices:
            raise ValueError("no choices in response")
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            raise ValueError("choices[0].message.content missing or not a string")
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
    except (ValueError, KeyError, TypeError) as e:
        msg = f"malformed response from {cfg.face_provider}: {e}"
        log_error("consult", msg)
        return tool_result_text(msg, is_error=True)

    # Cost estimate (rough — real cost tracked by provider dashboard)
    est_cost = (
        (prompt_tokens / 1000.0) * cfg.cost_per_1k_input
        + (completion_tokens / 1000.0) * cfg.cost_per_1k_output
    )
    # Fall back to a length-based estimate if usage is missing
    if prompt_tokens == 0 and completion_tokens == 0:
        approx_in = len(query) + (len(context) if context else 0) + len(system_prompt)
        approx_out = len(text)
        est_cost = (
            (approx_in / 4000.0) * cfg.cost_per_1k_input
            + (approx_out / 4000.0) * cfg.cost_per_1k_output
        )

    spent, calls, new_remaining = budget.charge(est_cost)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    log_info(
        "consult",
        f"face={cfg.face_name} model={cfg.face_model} "
        f"in_len={len(query)} ctx_len={len(context) if context else 0} "
        f"out_len={len(text)} pt={prompt_tokens} ct={completion_tokens} "
        f"cost_est=${est_cost:.5f} budget_spent=${spent:.4f} "
        f"remaining=${new_remaining:.4f} calls={calls} elapsed_ms={elapsed_ms}",
    )

    append_consult_log(
        cfg,
        {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "face": cfg.face_name,
            "provider": cfg.face_provider,
            "model": cfg.face_model,
            "query_len": len(query),
            "context_len": len(context) if context else 0,
            "response_len": len(text),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_est_usd": round(est_cost, 6),
            "budget_spent_usd": round(spent, 6),
            "budget_remaining_usd": round(new_remaining, 6),
            "calls_today": calls,
            "elapsed_ms": elapsed_ms,
        },
    )

    return tool_result_text(text, is_error=False)


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------
def make_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle_initialize(cfg: Config, params: dict[str, Any]) -> dict[str, Any]:
    client_version = None
    if isinstance(params, dict):
        client_version = params.get("protocolVersion")
    log_info(
        "rpc",
        f"initialize from client protocolVersion={client_version} "
        f"serverVersion={MCP_PROTOCOL_VERSION}",
    )
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            # Explicitly NO sampling capability advertised. Even so, we
            # reject sampling/* requests below as a belt-and-braces measure.
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


def handle_tools_list(cfg: Config) -> dict[str, Any]:
    return {"tools": [tool_schema(cfg)]}


def handle_tools_call(
    cfg: Config, budget: Budget, params: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (result, error_obj_without_id). Exactly one is not None."""
    if not isinstance(params, dict):
        return None, {"code": JSONRPC_INVALID_PARAMS, "message": "params must be an object"}
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(name, str):
        return None, {"code": JSONRPC_INVALID_PARAMS, "message": "'name' must be a string"}
    if not isinstance(args, dict):
        return None, {"code": JSONRPC_INVALID_PARAMS, "message": "'arguments' must be an object"}

    if name != cfg.tool_name:
        return None, {
            "code": JSONRPC_METHOD_NOT_FOUND,
            "message": f"unknown tool: {name}",
        }
    result = handle_consult(cfg, budget, args)
    return result, None


def dispatch(cfg: Config, budget: Budget, msg: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC request. Return a response dict, or None for notifications."""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    # FCT056 §8 #5 — refuse ALL sampling/* requests. This server NEVER lends
    # its compute back to anyone. If the upstream is compromised, this is
    # one of the lines it cannot cross.
    if isinstance(method, str) and method.startswith("sampling/"):
        log_warn(
            "security",
            f"refused {method} request (sampling lockdown — FCT056 §8 #5)",
        )
        if is_notification:
            return None
        return make_error(
            req_id,
            JSONRPC_METHOD_NOT_FOUND,
            f"sampling is disabled on {SERVER_NAME}: this server never consumes upstream LLM budget",
        )

    if method == "initialize":
        return make_response(req_id, handle_initialize(cfg, params))

    if method == "notifications/initialized":
        log_info("rpc", "client sent notifications/initialized")
        return None  # notification, no response

    if method == "tools/list":
        return make_response(req_id, handle_tools_list(cfg))

    if method == "tools/call":
        result, err = handle_tools_call(cfg, budget, params)
        if err is not None:
            return make_error(req_id, err["code"], err["message"])
        return make_response(req_id, result)

    if method == "ping":
        return make_response(req_id, {})

    if method in ("prompts/list", "resources/list", "resources/templates/list"):
        # Advertise empty lists so a capability-probing client sees nothing
        # rather than a hard error.
        return make_response(req_id, {method.split("/")[0]: []})

    if is_notification:
        log_info("rpc", f"ignoring unknown notification: {method}")
        return None

    return make_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"unknown method: {method}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def write_message(msg: dict[str, Any]) -> None:
    """Write a single JSON message as one line to stdout."""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_stdio_loop(cfg: Config, budget: Budget) -> int:
    log_info(
        "startup",
        f"{SERVER_NAME}/{SERVER_VERSION} ready: face={cfg.face_name} "
        f"model={cfg.face_model} provider={cfg.face_provider} "
        f"base_url={cfg.face_base_url} api_key_env={cfg.face_api_key_env} "
        f"budget=${cfg.budget_usd_daily:.2f}/day profile_dir={cfg.profile_dir}",
    )
    spent, calls, remaining = budget.snapshot()
    log_info(
        "startup",
        f"budget state: spent=${spent:.4f} calls={calls} remaining=${remaining:.4f}",
    )

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            log_error("rpc", f"parse error: {e}; line={line[:200]!r}")
            write_message(make_error(None, JSONRPC_PARSE_ERROR, f"parse error: {e}"))
            continue

        if not isinstance(msg, dict):
            write_message(make_error(None, JSONRPC_INVALID_REQUEST, "request must be an object"))
            continue

        try:
            response = dispatch(cfg, budget, msg)
        except Exception as e:  # noqa: BLE001 — keep the server alive at all costs
            log_error("rpc", f"internal error dispatching {msg.get('method')}: {type(e).__name__}: {e}")
            response = make_error(
                msg.get("id"),
                JSONRPC_INTERNAL_ERROR,
                f"internal error: {type(e).__name__}: {e}",
            )

        if response is not None:
            write_message(response)

    log_info("shutdown", "stdin closed; exiting cleanly")
    return 0


def main() -> int:
    cfg = Config()
    if not cfg.face_model:
        log_error("startup", "FACE_MODEL env var is required but missing or empty")
        return 2
    budget = Budget(cfg)
    try:
        return run_stdio_loop(cfg, budget)
    except KeyboardInterrupt:
        log_info("shutdown", "interrupted; exiting")
        return 0


if __name__ == "__main__":
    sys.exit(main())
