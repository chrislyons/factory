#!/usr/bin/env python3
"""
test-face-consultant-mcp.py — smoke test for face-consultant-mcp.py.

Exercises the MCP stdio server in-process (no subprocess, no real HTTP)
by importing its module and calling the dispatch functions directly with
a monkeypatched urllib HTTP layer. Intended to be runnable standalone:

    python3 /Users/nesbitt/dev/factory/scripts/test-face-consultant-mcp.py

Covers:
  1. initialize → protocolVersion + serverInfo
  2. tools/list → single tool, correct name + schema shape
  3. tools/call → happy path with mocked HTTP
  4. sampling/createMessage → JSON-RPC method-not-found refusal
  5. tools/call → budget exhausted path

Does NOT hit the network. Uses a temp HERMES_HOME so it never touches
real IG-88 profile state.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import types

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "face-consultant-mcp.py"


def load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("face_consultant_mcp", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module spec for {TARGET}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Mock HTTP layer
# ---------------------------------------------------------------------------
class MockResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def install_mock_http(mcp_mod: types.ModuleType, record: list[dict]) -> None:
    """Replace urllib.request.urlopen inside the mcp module with a mock."""

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        # Capture request details
        body_bytes = req.data if req.data is not None else b"{}"
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            body_json = {"_raw": body_bytes.decode("utf-8", errors="replace")}
        record.append(
            {
                "url": req.full_url,
                "headers": {k.lower(): v for k, v in req.headers.items()},
                "body": body_json,
            }
        )

        # Return a canned OpenAI-style completion
        payload = {
            "id": "mock-1",
            "object": "chat.completion",
            "created": 1700000000,
            "model": body_json.get("model", "mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "This is the mocked deliberative face's answer.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 17,
                "total_tokens": 59,
            },
        }
        return MockResponse(payload, 200)

    mcp_mod.urllib.request.urlopen = fake_urlopen  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test assertions
# ---------------------------------------------------------------------------
PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        msg = f"  FAIL  {name}" + (f" — {detail}" if detail else "")
        print(msg)
        FAILURES.append(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def run_tests() -> int:
    tmpdir = tempfile.mkdtemp(prefix="face-consultant-test-")
    os.environ["HERMES_HOME"] = tmpdir
    os.environ["FACE_NAME"] = "deliberative"
    os.environ["FACE_MODEL"] = "mock/model-v1"
    os.environ["FACE_PROVIDER"] = "mockrouter"
    os.environ["FACE_BASE_URL"] = "https://mock.invalid/api/v1"
    os.environ["FACE_API_KEY_ENV"] = "MOCK_API_KEY_FOR_TEST"
    os.environ["MOCK_API_KEY_FOR_TEST"] = "sk-test-not-real"
    os.environ["FACE_BUDGET_USD_DAILY"] = "1.00"
    os.environ["FACE_COST_PER_1K_INPUT_USD"] = "0.0005"
    os.environ["FACE_COST_PER_1K_OUTPUT_USD"] = "0.0015"
    os.environ["FACE_MAX_TOKENS_DEFAULT"] = "256"
    os.environ["FACE_TIMEOUT_SECONDS"] = "5"

    mcp = load_module()
    cfg = mcp.Config()
    budget = mcp.Budget(cfg)
    http_record: list[dict] = []
    install_mock_http(mcp, http_record)

    print(f"Using temp HERMES_HOME = {tmpdir}")
    print()

    # ---- Test 1: initialize ---------------------------------------------
    print("Test 1: initialize")
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
    }
    resp = mcp.dispatch(cfg, budget, req)
    check("response is a dict", isinstance(resp, dict))
    check("response has jsonrpc=2.0", resp.get("jsonrpc") == "2.0")
    check("response id echoed", resp.get("id") == 1)
    result = resp.get("result") or {}
    check("result.protocolVersion set", bool(result.get("protocolVersion")))
    check("result.serverInfo.name set", (result.get("serverInfo") or {}).get("name") == "face-consultant-mcp")
    check("result.capabilities.tools present", "tools" in (result.get("capabilities") or {}))
    check("result.capabilities.sampling NOT present", "sampling" not in (result.get("capabilities") or {}))
    print()

    # ---- Test 2: tools/list ---------------------------------------------
    print("Test 2: tools/list")
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = mcp.dispatch(cfg, budget, req)
    tools = ((resp or {}).get("result") or {}).get("tools") or []
    check("exactly one tool", len(tools) == 1, f"got {len(tools)}")
    if tools:
        t = tools[0]
        check("tool name is consult_deliberative", t.get("name") == "consult_deliberative")
        check("tool has description", bool(t.get("description")))
        schema = t.get("inputSchema") or {}
        check("schema is object type", schema.get("type") == "object")
        props = schema.get("properties") or {}
        check("schema has query prop", "query" in props)
        check("schema has context prop", "context" in props)
        check("schema has max_tokens prop", "max_tokens" in props)
        check("schema requires query", schema.get("required") == ["query"])
        check(
            "schema query is string",
            (props.get("query") or {}).get("type") == "string",
        )
    print()

    # ---- Test 3: tools/call happy path ----------------------------------
    print("Test 3: tools/call consult_deliberative (mocked HTTP)")
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "consult_deliberative",
            "arguments": {
                "query": "What is the current BTC regime?",
                "context": "volatility spiked 30% in the last hour",
                "max_tokens": 128,
            },
        },
    }
    resp = mcp.dispatch(cfg, budget, req)
    check("response is a dict", isinstance(resp, dict))
    check("no jsonrpc error", "error" not in (resp or {}))
    result = (resp or {}).get("result") or {}
    content = result.get("content") or []
    check("content has one item", len(content) == 1)
    if content:
        item = content[0]
        check("content[0].type == text", item.get("type") == "text")
        check(
            "content[0].text is the mocked answer",
            "mocked deliberative" in (item.get("text") or ""),
            f"got: {item.get('text')!r}",
        )
    check("isError is False", result.get("isError") is False)

    # Verify HTTP request was shaped correctly
    check("HTTP called exactly once", len(http_record) == 1)
    if http_record:
        call = http_record[0]
        check(
            "URL is chat/completions",
            call["url"].endswith("/chat/completions"),
            f"got {call['url']}",
        )
        check(
            "Authorization header present",
            "authorization" in call["headers"],
        )
        check(
            "Bearer token shape",
            str(call["headers"].get("authorization", "")).startswith("Bearer "),
        )
        check(
            "model matches FACE_MODEL",
            call["body"].get("model") == "mock/model-v1",
        )
        check("stream is False", call["body"].get("stream") is False)
        msgs = call["body"].get("messages") or []
        check(
            "messages contain system + context-system + user",
            len(msgs) == 3,
            f"got {len(msgs)}",
        )
        if len(msgs) == 3:
            check("msg[0] is system", msgs[0].get("role") == "system")
            check("msg[1] is system (context)", msgs[1].get("role") == "system")
            check(
                "msg[1] contains context text",
                "volatility spiked" in (msgs[1].get("content") or ""),
            )
            check("msg[2] is user", msgs[2].get("role") == "user")
            check(
                "msg[2] content is query",
                "BTC regime" in (msgs[2].get("content") or ""),
            )

    # Budget should have been charged
    spent, calls, remaining = budget.snapshot()
    check("budget.calls == 1 after one consult", calls == 1, f"got {calls}")
    check("budget.spent > 0", spent > 0.0, f"got {spent}")
    check("budget.remaining < daily cap", remaining < 1.00)

    # Consult log file should have one line
    log_path = pathlib.Path(tmpdir) / "consult-log.jsonl"
    check("consult-log.jsonl exists", log_path.exists())
    if log_path.exists():
        lines = log_path.read_text().strip().splitlines()
        check("one log line", len(lines) == 1)
        if lines:
            rec = json.loads(lines[0])
            check("log record has face", rec.get("face") == "deliberative")
            check("log record has model", rec.get("model") == "mock/model-v1")
            check("log record has cost_est_usd", "cost_est_usd" in rec)
            check("log record has prompt_tokens", rec.get("prompt_tokens") == 42)
            check("log record has completion_tokens", rec.get("completion_tokens") == 17)
    print()

    # ---- Test 4: sampling/createMessage is refused ----------------------
    print("Test 4: sampling/createMessage is refused")
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "sampling/createMessage",
        "params": {
            "messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}],
            "maxTokens": 100,
        },
    }
    resp = mcp.dispatch(cfg, budget, req)
    check("response has error", isinstance(resp, dict) and "error" in resp)
    if resp and "error" in resp:
        err = resp["error"]
        check(
            "error code is -32601 (method not found)",
            err.get("code") == -32601,
            f"got {err.get('code')}",
        )
        check(
            "error message mentions sampling",
            "sampling" in (err.get("message") or "").lower(),
        )
    # Also test the generic sampling/* prefix
    req2 = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "sampling/somethingElse",
        "params": {},
    }
    resp2 = mcp.dispatch(cfg, budget, req2)
    check(
        "sampling/* generic is also refused",
        isinstance(resp2, dict) and resp2.get("error", {}).get("code") == -32601,
    )
    print()

    # ---- Test 5: budget exhausted ---------------------------------------
    print("Test 5: budget exhausted path")
    # Manually drain the budget file
    drain_path = pathlib.Path(tmpdir) / "consult-budget.json"
    import datetime as _dt

    drain_path.write_text(
        json.dumps(
            {
                "date": _dt.date.today().isoformat(),
                "spent_usd": 99.99,
                "calls": 9999,
            }
        )
    )
    http_record.clear()
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "consult_deliberative",
            "arguments": {"query": "Should not be called"},
        },
    }
    resp = mcp.dispatch(cfg, budget, req)
    check("response is not an error at JSON-RPC level", "error" not in (resp or {}))
    result = (resp or {}).get("result") or {}
    check("tool result isError is True", result.get("isError") is True)
    content = result.get("content") or []
    if content:
        txt = (content[0] or {}).get("text") or ""
        check("result text mentions budget", "budget" in txt.lower())
    check("no HTTP call made when budget exhausted", len(http_record) == 0)
    print()

    # ---- Test 6: unknown tool name ---------------------------------------
    print("Test 6: tools/call with unknown tool name")
    # Restore budget for this test
    drain_path.write_text(
        json.dumps(
            {
                "date": _dt.date.today().isoformat(),
                "spent_usd": 0.0,
                "calls": 0,
            }
        )
    )
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "consult_nonexistent", "arguments": {"query": "x"}},
    }
    resp = mcp.dispatch(cfg, budget, req)
    check(
        "unknown tool → JSON-RPC method-not-found error",
        isinstance(resp, dict)
        and resp.get("error", {}).get("code") == -32601,
    )
    print()

    # ---- Test 7: initialize notification handling -----------------------
    print("Test 7: notifications/initialized returns None")
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = mcp.dispatch(cfg, budget, note)
    check("notification yields no response", resp is None)
    print()

    # ---- Summary ---------------------------------------------------------
    print("=" * 60)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    if FAIL:
        print()
        print("Failures:")
        for f in FAILURES:
            print(f)
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
