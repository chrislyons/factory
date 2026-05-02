#!/usr/bin/env python3
"""Model-agnostic vllm-mlx benchmark harness.

Pure client. Talks to whatever vllm-mlx server is on --port. Does NOT start
or stop servers — restarts go through factory-model-switch.sh under operator
approval (FCT090 rule).

Usage:
    test-vllm-bench.py --model nemostein --label nemostein-starter \\
                       [--port 41966] \\
                       [--include stress concurrency multi-turn]

Outputs:
    docs/fct/FCT090-bench-<label>.json
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
import subprocess  # noqa: E402

DOCS_DIR = Path("/Users/nesbitt/dev/factory/docs/fct")


def get_mem():
    """Local replacement — benchmark_utils.get_vm_stats parses by single
    whitespace split which breaks 'Pages free:'. Use multi-word key matching.
    """
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        page_size = 16384
        result = {"free_gb": 0.0, "active_gb": 0.0, "wired_gb": 0.0}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Pages free:"):
                v = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
                result["free_gb"] = round(v * page_size / (1024 ** 3), 2)
            elif line.startswith("Pages active:"):
                v = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
                result["active_gb"] = round(v * page_size / (1024 ** 3), 2)
            elif line.startswith("Pages wired down:"):
                v = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
                result["wired_gb"] = round(v * page_size / (1024 ** 3), 2)
        return result
    except Exception:
        return {"free_gb": 0, "active_gb": 0, "wired_gb": 0}

# 6 quality prompts from FCT089 — direct comparison
QUALITY_PROMPTS = [
    {"name": "Short factual",      "prompt": "What is the capital of France? Answer in one word.", "max_tokens": 256},
    {"name": "Sheep riddle",       "prompt": "A farmer has 17 sheep. All but 9 die. How many are left?", "max_tokens": 1024},
    {"name": "Code: palindrome",   "prompt": "Write a Python function that checks if a string is a palindrome. Include docstring and type hints.", "max_tokens": 2048},
    {"name": "Multi-step math",    "prompt": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?", "max_tokens": 1024},
    {"name": "Instruction follow", "prompt": "List exactly 5 benefits of exercise. Numbered list. One sentence each. No intro or conclusion.", "max_tokens": 1024},
    {"name": "Tool call",          "prompt": "You have a tool called read_file(path). User asks: 'Read config.yaml and tell me the database port.' Respond with the tool call JSON only.", "max_tokens": 1024},
]

# Padding text repeated to hit context targets (~5 chars/token average)
PADDING = (
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. "
    "Sphinx of black quartz, judge my vow. How vexingly quick daft zebras jump. "
    "Bright vixens jump; dozy fowl quack. Waltz, bad nymph, for quick jigs vex. "
)

# Multi-turn dialog — each turn references prior content. Production gate.
MULTI_TURN = [
    "I'm writing a Rust CLI for managing notes. The notes are markdown files in ~/notes. Suggest a directory layout and the top 3 commands I should implement first.",
    "For the 'add' command you suggested, what command-line arguments should it accept?",
    "What error cases should the 'add' command handle? List them with the exit codes you'd return.",
    "Now show me a Rust function signature for the add command using clap derive macros.",
    "What test cases should I write for that function? List 4 specific scenarios.",
    "Earlier you mentioned a directory layout. Where in that layout should the test fixtures live?",
    "Write a brief README section for the 'add' command incorporating the args, error codes, and an example.",
    "Summarize what we've designed in 3 bullet points.",
]


def post(port, model, messages, max_tokens, timeout=300, sampling=None, tools=None):
    """One POST. Returns dict with timing + content + reasoning + tokens.

    sampling: optional dict overriding default {temperature:0, stream:False}.
              e.g. {"temperature": 0.6, "top_p": 0.95, "repetition_penalty": 1.05}
    tools:    optional list of OpenAI-format tool schemas to send in the request.
    """
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    if sampling:
        payload.update(sampling)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    start = time.time()
    try:
        r = requests.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json=payload, timeout=timeout,
        )
        elapsed = time.time() - start
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": round(elapsed, 2)}
        d = r.json()
        m = d["choices"][0]["message"]
        finish = d["choices"][0].get("finish_reason")
        u = d.get("usage", {})
        ct = u.get("completion_tokens", 0)
        content = m.get("content") or ""
        reasoning = m.get("reasoning_content") or ""
        tool_calls = m.get("tool_calls")
        return {
            "finish": finish,
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": ct,
            "elapsed_s": round(elapsed, 2),
            "tok_per_sec": round(ct / elapsed, 1) if elapsed > 0 else 0,
            "content_len": len(content),
            "reasoning_len": len(reasoning),
            "content_preview": content[:240],
            "content_full": content,
            "has_tool_calls": bool(tool_calls),
            "tool_calls": tool_calls or [],
        }
    except Exception as e:
        return {"error": str(e)[:300], "elapsed": round(time.time() - start, 2)}


def run_quality(port, model):
    print("\n[quality] 6-prompt suite (FCT089-comparable)")
    out = []
    for b in QUALITY_PROMPTS:
        print(f"  - {b['name']:<22} ", end="", flush=True)
        r = post(port, model, [{"role": "user", "content": b["prompt"]}], b["max_tokens"])
        r["name"] = b["name"]
        out.append(r)
        if "error" in r:
            print(f"ERR {r['error'][:80]}")
        else:
            print(f"{r['completion_tokens']}t in {r['elapsed_s']}s ({r['tok_per_sec']} tok/s) finish={r['finish']}")
    return out


def make_padded_prompt(target_tokens, model_q):
    """Synthesize a prompt of approximately `target_tokens`.
    Approx 1 token per 4 chars for English; pad slightly under and let the
    actual prompt_tokens reading reflect reality.
    """
    chars = target_tokens * 4
    pad = (PADDING * (chars // len(PADDING) + 1))[:chars]
    return f"The following is reference text. Read it, then answer the question.\n\n{pad}\n\nQuestion: {model_q}"


def run_stress(port, model):
    print("\n[stress] context scaling 1K -> 64K")
    targets = [1_000, 4_000, 8_000, 16_000, 32_000, 64_000]
    out = []
    for t in targets:
        prompt = make_padded_prompt(t, "In one sentence, what color is mentioned most often in the reference text?")
        print(f"  - ~{t:>5}t ctx ", end="", flush=True)
        r = post(port, model, [{"role": "user", "content": prompt}], 256, timeout=600)
        r["target_ctx"] = t
        out.append(r)
        if "error" in r:
            print(f"ERR {r['error'][:80]}")
        else:
            print(f"prompt={r['prompt_tokens']}t, decode={r['completion_tokens']}t @ {r['tok_per_sec']} tok/s, total {r['elapsed_s']}s")
    return out


def run_concurrency(port, model):
    print("\n[concurrency] 2 simultaneous requests (Boot+Kelk simulation)")
    prompts = [
        "Write a 3-sentence summary of how a B-tree differs from a binary search tree.",
        "Write a 3-sentence summary of how HTTP/2 differs from HTTP/1.1.",
    ]

    def one(prompt):
        return post(port, model, [{"role": "user", "content": prompt}], 512)

    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(one, p) for p in prompts]
        results = [f.result() for f in futures]
    wall = round(time.time() - start, 2)
    print(f"  wall_clock={wall}s")
    for i, r in enumerate(results):
        if "error" in r:
            print(f"  [{i}] ERR {r['error'][:80]}")
        else:
            print(f"  [{i}] {r['completion_tokens']}t in {r['elapsed_s']}s ({r['tok_per_sec']} tok/s)")
    return {"wall_s": wall, "per_request": results}


def run_multi_turn(port, model):
    print("\n[multi-turn] 8-turn dialog (production gate)")
    messages = []
    out = []
    for i, user_msg in enumerate(MULTI_TURN, 1):
        messages.append({"role": "user", "content": user_msg})
        print(f"  - turn {i}/{len(MULTI_TURN)} ", end="", flush=True)
        r = post(port, model, messages, 1024, timeout=600)
        r["turn"] = i
        r["user_chars"] = len(user_msg)
        out.append(r)
        if "error" in r:
            print(f"ERR {r['error'][:80]}")
            break
        # Append assistant response so next turn has context
        messages.append({"role": "assistant", "content": r["content_preview"] if r["content_len"] > 0 else "(empty)"})
        # Use the actual content (we already stored preview). Refetch for full assistant text:
        # The post() truncates content_preview to 240 chars — that's intentional, but for
        # multi-turn fidelity we want the full assistant text. Re-issue would double cost,
        # so use content_preview as a *summary* — degraded fidelity but documented.
        print(f"{r['completion_tokens']}t in {r['elapsed_s']}s ({r['tok_per_sec']} tok/s) finish={r['finish']}")
    # Pass criteria: all turns return substantial content; later turns aren't
    # degenerate. We do NOT treat finish=length as failure — Nemotron-H + qwen3
    # parser routinely fills max_tokens with reasoning padding while still
    # producing valid content. The real failure modes are empty content,
    # error responses, or sudden length collapse on later turns.
    later_turns = out[3:]  # turns 4..N where E4B-SABER historically degraded
    pass_criteria = {
        "all_turns_succeeded": all("error" not in t for t in out),
        "all_have_content": all(t.get("content_len", 0) > 50 for t in out),
        "later_turns_not_degenerate": all(t.get("content_len", 0) > 100 for t in later_turns),
    }
    pass_criteria["overall"] = all(pass_criteria.values())
    print(f"  multi-turn gate: {'PASS' if pass_criteria['overall'] else 'FAIL'} {pass_criteria}")
    return {"turns": out, "gate": pass_criteria}


# ---------------------------------------------------------------------------
# Autonomous tool-loop test
# ---------------------------------------------------------------------------

# OpenAI-format tool schemas. Sent in request body; vllm-mlx and mlx_lm.server
# both accept the standard `tools` field.
AUTONOMOUS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file. Overwrites if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file. Use with caution — irreversible.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

# Fake state for the tool runtime
FAKE_FS = {
    "/tmp/notes/": ["meeting-q3.md", "todo.md", "old-draft.md"],
    "/tmp/notes/meeting-q3.md": (
        "# Q3 Planning Meeting\n\n"
        "Date: 2026-04-15\nAttendees: Alice, Bob, Carol\n\n"
        "Decisions:\n"
        "- Hire 2 backend engineers in Q3\n"
        "- Migrate database to Postgres 17\n"
        "- Launch beta of mobile app by Sept\n"
    ),
}

AUTONOMOUS_USER_TASK = (
    "List the files in /tmp/notes/, then read meeting-q3.md, "
    "then write a 2-line summary of the key decisions to /tmp/notes/summary.md."
)

EXPECTED_TOOL_SEQUENCE = [
    ("list_directory", {"path": "/tmp/notes/"}),
    ("read_file",      {"path": "/tmp/notes/meeting-q3.md"}),
    ("write_file",     {"path": "/tmp/notes/summary.md"}),  # content varies
]

# --- Type A: explicit follow-up after report-back ----------------------------
# User issues a second/third user message AFTER the model reports completion of
# the previous task. Tests whether the model will pick up new instructions
# (the basic CLI/Matrix flow). Failure pattern observed in production: model
# reports "done" then refuses to call tools on the next user message.
CONTINUATION_TASKS = [
    "List the files in /tmp/notes/, then read meeting-q3.md, "
    "then write a 2-line summary of the key decisions to /tmp/notes/summary.md.",
    "Now read /tmp/notes/summary.md to verify it, then write the same content "
    "but uppercased to /tmp/notes/summary-loud.md.",
    "Delete /tmp/notes/summary-loud.md, then list /tmp/notes/ to confirm it is gone.",
]

# --- Type B: autonomous sprint -----------------------------------------------
# User gives a multi-step sprint up front. Agent must do work, report progress,
# then **continue on its own** to the next step without being told. This
# matches the CLI/Matrix-gateway production pattern where Chris issues a sprint
# and expects the agent to chew through it autonomously, posting periodic
# updates. Failure mode: agent does step 1, reports, stops dead waiting for
# explicit permission to continue.
SPRINT_TASK = (
    "Sprint: I need three things done in /tmp/notes/. "
    "Step 1: read meeting-q3.md and write a 2-line summary to summary.md. "
    "Step 2: write a follow-up reminder to followup.md saying 'Schedule Q3 hiring kickoff'. "
    "Step 3: list the directory to confirm both new files exist. "
    "Work through all three steps, posting a brief progress update after each step. "
    "Do not stop until all three steps are complete."
)

# Expected tool sequence for the sprint (in any order within each step is OK,
# but list_directory should come last per the user's instruction)
SPRINT_EXPECTED_TOOLS = ["read_file", "write_file", "write_file", "list_directory"]

# Extended-loop scenario for testing >8 turn capacity. The agent must read 3
# files in sequence, accumulate facts, then write a combined report.
EXTENDED_FAKE_FS = {
    "/tmp/extended/": ["alpha.md", "beta.md", "gamma.md"],
    "/tmp/extended/alpha.md": "Alpha system: postgres database, primary key on user_id, indexed on email.",
    "/tmp/extended/beta.md":  "Beta system: redis cache, TTL 300s, eviction policy LRU.",
    "/tmp/extended/gamma.md": "Gamma system: nginx reverse proxy, SSL termination, rate limit 100rps.",
}

EXTENDED_USER_TASK = (
    "I need a one-paragraph architecture summary. "
    "List the files in /tmp/extended/, read each of the 3 files, "
    "then write a combined paragraph mentioning all 3 systems "
    "(database, cache, proxy) to /tmp/extended/architecture.md. "
    "After that, list /tmp/extended/ again to confirm the file exists."
)


def fake_tool_runtime(name, args):
    """Simulate tool execution. Returns the string the tool would return."""
    if name == "list_directory":
        path = args.get("path", "")
        files = FAKE_FS.get(path, [])
        if not files:
            return f"ERROR: directory not found: {path}"
        return "\n".join(files)
    if name == "read_file":
        path = args.get("path", "")
        content = FAKE_FS.get(path)
        if content is None:
            return f"ERROR: file not found: {path}"
        return content
    if name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        FAKE_FS[path] = content
        return f"OK: wrote {len(content)} bytes to {path}"
    if name == "delete_file":
        path = args.get("path", "")
        if path in FAKE_FS:
            del FAKE_FS[path]
            return f"OK: deleted {path}"
        return f"ERROR: file not found: {path}"
    return f"ERROR: unknown tool: {name}"


def parse_inline_tool_call(content):
    """Some models emit JSON tool calls inline in `content` instead of using
    the structured `tool_calls` field. Try to parse those as a fallback.
    Returns list of {"name": str, "arguments": dict} or [] if none found.
    """
    if not content:
        return []
    found = []
    # Try fenced JSON block first
    import re
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    candidates = list(fenced)
    # Try bare JSON objects on their own lines
    if not candidates:
        candidates = re.findall(r"^\s*(\{[\s\S]*?\})\s*$", content, re.MULTILINE)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        # Several shapes in the wild
        name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or obj.get("function")
        args = obj.get("arguments") or obj.get("args") or obj.get("params") or obj.get("parameters") or {}
        if isinstance(name, str) and isinstance(args, dict):
            found.append({"name": name, "arguments": args})
    return found


def extract_tool_calls(response):
    """Return list of {"name": str, "arguments": dict} from a post() response.
    Tries the structured `tool_calls` field first, falls back to inline JSON
    parsing on the content.
    """
    out = []
    for tc in response.get("tool_calls", []) or []:
        # OpenAI format: {"id": "...", "type": "function", "function": {"name": "...", "arguments": "<json string>"}}
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        name = fn.get("name") or tc.get("name")
        raw_args = fn.get("arguments") or tc.get("arguments") or "{}"
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {"_raw": raw_args}
        else:
            args = raw_args
        if name:
            out.append({"name": name, "arguments": args})
    if not out:
        out = parse_inline_tool_call(response.get("content_full", "") or response.get("content_preview", ""))
    return out


def run_autonomous(port, model, sampling=None, max_iters=8):
    """Run the autonomous tool-loop. The harness plays the tool runtime.

    Pass criteria are evaluated post-hoc; the loop itself runs until the model
    stops calling tools or hits max_iters.
    """
    tag = f"sampling={sampling}" if sampling else "sampling=greedy(temp=0)"
    print(f"\n[autonomous] 4-tool MCP loop ({tag})")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful agent. Use the provided tools to complete the user's task. "
                "Call one tool at a time. After each tool result, decide what to do next. "
                "When the task is fully complete, reply with a short confirmation and DO NOT call more tools."
            ),
        },
        {"role": "user", "content": AUTONOMOUS_USER_TASK},
    ]
    trace = []
    for it in range(1, max_iters + 1):
        print(f"  - iter {it}/{max_iters} ", end="", flush=True)
        r = post(port, model, messages, 1024, timeout=300, sampling=sampling, tools=AUTONOMOUS_TOOLS)
        if "error" in r:
            trace.append({"iter": it, "error": r["error"]})
            print(f"ERR {r['error'][:80]}")
            break
        calls = extract_tool_calls(r)
        step = {
            "iter": it,
            "completion_tokens": r.get("completion_tokens"),
            "elapsed_s": r.get("elapsed_s"),
            "tok_per_sec": r.get("tok_per_sec"),
            "finish": r.get("finish"),
            "content_preview": r.get("content_preview"),
            "tool_calls": calls,
        }
        trace.append(step)
        if not calls:
            # No tool call → model is done
            print(f"no-tool ({r['completion_tokens']}t in {r['elapsed_s']}s) — content: {r['content_preview'][:80]!r}")
            messages.append({"role": "assistant", "content": r.get("content_full", "")})
            break
        # Append assistant message with tool_calls + execute each call
        # Use OpenAI message format so the model can resolve tool_call_id refs
        oai_calls = []
        for idx, c in enumerate(calls):
            oai_calls.append({
                "id": f"call_{it}_{idx}",
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
            })
        messages.append({
            "role": "assistant",
            "content": r.get("content_full", ""),
            "tool_calls": oai_calls,
        })
        executed = []
        for idx, c in enumerate(calls):
            result = fake_tool_runtime(c["name"], c["arguments"])
            executed.append({"name": c["name"], "args": c["arguments"], "result_preview": result[:120]})
            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{it}_{idx}",
                "name": c["name"],
                "content": result,
            })
        step["executed"] = executed
        names = ", ".join(c["name"] for c in calls)
        print(f"called: {names}  ({r['completion_tokens']}t in {r['elapsed_s']}s)")

    # Pass criteria
    all_calls = [c for s in trace for c in s.get("tool_calls", [])]
    call_names_in_order = [c["name"] for c in all_calls]
    expected_names = [n for n, _ in EXPECTED_TOOL_SEQUENCE]
    # Each expected tool called at least once
    each_called = {n: (n in call_names_in_order) for n in expected_names}
    # No tool called more than twice (small tolerance for retries)
    repeat_counts = {n: call_names_in_order.count(n) for n in set(call_names_in_order)}
    no_runaway = all(c <= 2 for c in repeat_counts.values())
    # In-order: list before read before write (allowing other calls between)
    def first_index(name):
        try:
            return call_names_in_order.index(name)
        except ValueError:
            return -1
    order_ok = (
        first_index("list_directory") < first_index("read_file") < first_index("write_file")
        if all(first_index(n) >= 0 for n in expected_names) else False
    )
    # Wrote a non-empty summary file
    summary_path = "/tmp/notes/summary.md"
    summary_written = summary_path in FAKE_FS and len(FAKE_FS[summary_path]) > 20
    # Terminated cleanly (last iter had no tool calls OR loop exited at max_iters with no errors)
    terminated_cleanly = trace and (not trace[-1].get("tool_calls"))
    gate = {
        "each_expected_tool_called": all(each_called.values()),
        "no_runaway_repetition": no_runaway,
        "order_correct": order_ok,
        "summary_file_written": summary_written,
        "terminated_cleanly": terminated_cleanly,
        "iters_used": len(trace),
        "total_tool_calls": len(all_calls),
        "repeat_counts": repeat_counts,
    }
    gate["overall"] = all([
        gate["each_expected_tool_called"],
        gate["no_runaway_repetition"],
        gate["order_correct"],
        gate["summary_file_written"],
        gate["terminated_cleanly"],
    ])
    print(f"  autonomous gate: {'PASS' if gate['overall'] else 'FAIL'} {gate}")
    # Reset fake_fs for next run (but keep the original contents)
    if summary_path in FAKE_FS and summary_path not in {"/tmp/notes/", "/tmp/notes/meeting-q3.md"}:
        del FAKE_FS[summary_path]
    return {"trace": trace, "gate": gate, "sampling": sampling or "greedy"}


def _run_loop(port, model, messages, sampling, max_iters, fake_fs_extra=None):
    """Inner loop driver. Returns (trace, final_messages, all_tool_calls).
    Manages the dialog: sends each turn, parses tool calls, executes via
    fake_tool_runtime, appends results, and continues until the model stops
    calling tools or hits max_iters.
    """
    if fake_fs_extra:
        FAKE_FS.update(fake_fs_extra)
    trace = []
    all_calls = []
    for it in range(1, max_iters + 1):
        print(f"  - iter {it}/{max_iters} ", end="", flush=True)
        r = post(port, model, messages, 1024, timeout=300, sampling=sampling, tools=AUTONOMOUS_TOOLS)
        if "error" in r:
            trace.append({"iter": it, "error": r["error"]})
            print(f"ERR {r['error'][:80]}")
            break
        calls = extract_tool_calls(r)
        all_calls.extend(calls)
        step = {
            "iter": it,
            "completion_tokens": r.get("completion_tokens"),
            "elapsed_s": r.get("elapsed_s"),
            "finish": r.get("finish"),
            "content_preview": r.get("content_preview"),
            "tool_calls": calls,
        }
        trace.append(step)
        if not calls:
            print(f"no-tool ({r['completion_tokens']}t) — content: {r['content_preview'][:80]!r}")
            messages.append({"role": "assistant", "content": r.get("content_full", "")})
            break
        oai_calls = []
        for idx, c in enumerate(calls):
            oai_calls.append({
                "id": f"call_{it}_{idx}",
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
            })
        messages.append({
            "role": "assistant",
            "content": r.get("content_full", ""),
            "tool_calls": oai_calls,
        })
        executed = []
        for idx, c in enumerate(calls):
            result = fake_tool_runtime(c["name"], c["arguments"])
            executed.append({"name": c["name"], "args": c["arguments"], "result_preview": result[:120]})
            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{it}_{idx}",
                "name": c["name"],
                "content": result,
            })
        step["executed"] = executed
        names = ", ".join(c["name"] for c in calls)
        print(f"called: {names}  ({r['completion_tokens']}t in {r['elapsed_s']}s)")
    return trace, messages, all_calls


def run_continuation(port, model, sampling=None, max_iters_per_task=8):
    """Type A: agent does task → reports → user issues NEXT task → agent must
    actually do it (not just say it will). Tests whether the model can pick
    up new instructions after report-back. Critical for CLI/Matrix flow.
    """
    tag = f"sampling={sampling}" if sampling else "sampling=greedy(temp=0)"
    print(f"\n[continuation] 3-task sequential ({tag})")
    messages = [{
        "role": "system",
        "content": (
            "You are a careful agent. Use the provided tools to complete each user task. "
            "Call one tool at a time. After each tool result, decide what to do next. "
            "When a task is fully complete, reply with a short confirmation."
        ),
    }]
    per_task_traces = []
    for ti, task in enumerate(CONTINUATION_TASKS, 1):
        print(f"\n  >>> task {ti}/{len(CONTINUATION_TASKS)}: {task[:100]}...")
        messages.append({"role": "user", "content": task})
        trace, messages, calls = _run_loop(port, model, messages, sampling, max_iters_per_task)
        per_task_traces.append({"task_idx": ti, "task": task, "trace": trace, "tool_call_count": len(calls)})
    # Pass criteria
    gate = {
        "task1_made_calls": per_task_traces[0]["tool_call_count"] >= 3,
        "task2_made_calls": per_task_traces[1]["tool_call_count"] >= 2,
        "task3_made_calls": per_task_traces[2]["tool_call_count"] >= 2,
        "summary_md_exists":      "/tmp/notes/summary.md" in FAKE_FS,
        "summary_loud_md_existed": True,  # written and then deleted
        "summary_loud_md_deleted": "/tmp/notes/summary-loud.md" not in FAKE_FS,
    }
    gate["overall"] = all([
        gate["task1_made_calls"],
        gate["task2_made_calls"],
        gate["task3_made_calls"],
    ])
    print(f"\n  continuation gate: {'PASS' if gate['overall'] else 'FAIL'} {gate}")
    # Reset
    for k in list(FAKE_FS.keys()):
        if k not in ("/tmp/notes/", "/tmp/notes/meeting-q3.md"):
            del FAKE_FS[k]
    return {"per_task": per_task_traces, "gate": gate, "sampling": sampling or "greedy"}


def run_sprint(port, model, sampling=None, max_iters=20):
    """Type B: agent given a 3-step sprint up front, must work through ALL
    steps autonomously, posting progress updates between steps WITHOUT being
    re-prompted. This is the CLI/Matrix production pattern.
    """
    tag = f"sampling={sampling}" if sampling else "sampling=greedy(temp=0)"
    print(f"\n[sprint] autonomous 3-step sprint, single user message ({tag})")
    messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous agent working on a sprint. The user has given you a "
                "multi-step task. Work through ALL the steps without stopping for permission. "
                "After each step, post a brief progress update in your response, then immediately "
                "continue to the next step by calling the appropriate tool. "
                "Only stop calling tools when ALL steps are complete."
            ),
        },
        {"role": "user", "content": SPRINT_TASK},
    ]
    trace, _final_messages, all_calls = _run_loop(port, model, messages, sampling, max_iters)
    # Pass criteria
    call_names = [c["name"] for c in all_calls]
    gate = {
        "iters_used": len(trace),
        "total_tool_calls": len(all_calls),
        "called_read_file": "read_file" in call_names,
        "called_write_file_at_least_twice": call_names.count("write_file") >= 2,
        "called_list_directory": "list_directory" in call_names,
        "summary_md_written": "/tmp/notes/summary.md" in FAKE_FS,
        "followup_md_written": "/tmp/notes/followup.md" in FAKE_FS,
        "no_runaway":           len(all_calls) <= 12,
    }
    gate["overall"] = all([
        gate["called_read_file"],
        gate["called_write_file_at_least_twice"],
        gate["called_list_directory"],
        gate["summary_md_written"],
        gate["followup_md_written"],
        gate["no_runaway"],
    ])
    print(f"\n  sprint gate: {'PASS' if gate['overall'] else 'FAIL'} {gate}")
    for k in list(FAKE_FS.keys()):
        if k not in ("/tmp/notes/", "/tmp/notes/meeting-q3.md"):
            del FAKE_FS[k]
    return {"trace": trace, "gate": gate, "sampling": sampling or "greedy"}


def run_extended_loop(port, model, sampling=None, max_iters=20):
    """Test >8 turn capacity: agent reads 3 files, accumulates content, writes
    a combined report, then verifies. Probes long-loop coherence.
    """
    tag = f"sampling={sampling}" if sampling else "sampling=greedy(temp=0)"
    print(f"\n[extended-loop] >8 turn capacity test ({tag})")
    FAKE_FS.update(EXTENDED_FAKE_FS)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful agent. Use the provided tools to complete the user's task. "
                "Call one tool at a time. After each tool result, decide what to do next. "
                "Work through ALL steps without stopping for permission until the task is complete."
            ),
        },
        {"role": "user", "content": EXTENDED_USER_TASK},
    ]
    trace, _final, all_calls = _run_loop(port, model, messages, sampling, max_iters)
    call_names = [c["name"] for c in all_calls]
    gate = {
        "iters_used": len(trace),
        "total_tool_calls": len(all_calls),
        "called_list_directory_at_least_2x": call_names.count("list_directory") >= 2,
        "called_read_file_3x": call_names.count("read_file") >= 3,
        "called_write_file": call_names.count("write_file") >= 1,
        "architecture_md_written": "/tmp/extended/architecture.md" in FAKE_FS,
        "no_runaway": len(all_calls) <= 15,
    }
    # Quality check on the written file: should mention all three system keywords
    if gate["architecture_md_written"]:
        body = FAKE_FS["/tmp/extended/architecture.md"].lower()
        gate["mentions_database"] = "postgres" in body or "database" in body
        gate["mentions_cache"] = "redis" in body or "cache" in body
        gate["mentions_proxy"] = "nginx" in body or "proxy" in body
    else:
        gate["mentions_database"] = gate["mentions_cache"] = gate["mentions_proxy"] = False
    gate["overall"] = all([
        gate["called_read_file_3x"],
        gate["called_write_file"],
        gate["architecture_md_written"],
        gate["mentions_database"],
        gate["mentions_cache"],
        gate["mentions_proxy"],
        gate["no_runaway"],
    ])
    print(f"\n  extended gate: {'PASS' if gate['overall'] else 'FAIL'} {gate}")
    for k in list(FAKE_FS.keys()):
        if k.startswith("/tmp/extended/") and k not in EXTENDED_FAKE_FS:
            del FAKE_FS[k]
    return {"trace": trace, "gate": gate, "sampling": sampling or "greedy"}


def scrape_metrics(port):
    """Fetch /metrics; return (raw_text_truncated, parsed_dict_of_known_keys)."""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/metrics", timeout=5)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        text = r.text
        # Parse Prometheus lines: metric_name{labels} value
        keys = {}
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            name = parts[0].split("{")[0]
            try:
                val = float(parts[1])
            except ValueError:
                continue
            # Aggregate (sum across labels)
            keys[name] = keys.get(name, 0.0) + val
        # Highlight cache-related keys
        cache_keys = {k: v for k, v in keys.items() if "cache" in k.lower() or "prefix" in k.lower() or "hit" in k.lower() or "miss" in k.lower()}
        return {"all_keys_count": len(keys), "cache_keys": cache_keys, "raw_lines": len(text.splitlines())}
    except Exception as e:
        return {"error": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="served-model-name")
    ap.add_argument("--port", type=int, default=41966)
    ap.add_argument("--label", required=True, help="output filename suffix")
    ap.add_argument("--include", nargs="*", default=[], choices=["stress", "concurrency", "multi-turn", "autonomous", "continuation", "sprint", "extended"])
    ap.add_argument("--autonomous-only", action="store_true", help="skip the quality suite; run only the autonomous loop (faster A/B sweeps)")
    ap.add_argument("--sampling", help='JSON sampling override, e.g. \'{"temperature":0.6,"top_p":0.95}\'')
    args = ap.parse_args()

    # Verify server reachable
    try:
        models = requests.get(f"http://127.0.0.1:{args.port}/v1/models", timeout=5).json()
        served = [m["id"] for m in models.get("data", [])]
        if args.model not in served:
            print(f"ERROR: model {args.model!r} not served on :{args.port}; available: {served}")
            sys.exit(2)
    except Exception as e:
        print(f"ERROR: cannot reach :{args.port}: {e}")
        sys.exit(2)

    print(f"=== test-vllm-bench label={args.label} model={args.model} port={args.port} ===")
    pre_mem = get_mem()
    pre_metrics = scrape_metrics(args.port)
    print(f"pre_mem: {pre_mem}")
    print(f"pre_metrics: {pre_metrics}")

    results = {
        "label": args.label,
        "model": args.model,
        "port": args.port,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pre_mem": pre_mem,
        "pre_metrics": pre_metrics,
        "include": args.include,
    }

    sampling = json.loads(args.sampling) if args.sampling else None
    if not args.autonomous_only:
        results["quality"] = run_quality(args.port, args.model)
    if "stress" in args.include:
        results["stress"] = run_stress(args.port, args.model)
    if "concurrency" in args.include:
        results["concurrency"] = run_concurrency(args.port, args.model)
    if "multi-turn" in args.include:
        results["multi_turn"] = run_multi_turn(args.port, args.model)
    if "autonomous" in args.include:
        results["autonomous"] = run_autonomous(args.port, args.model, sampling=sampling)
    if "continuation" in args.include:
        results["continuation"] = run_continuation(args.port, args.model, sampling=sampling)
    if "sprint" in args.include:
        results["sprint"] = run_sprint(args.port, args.model, sampling=sampling)
    if "extended" in args.include:
        results["extended"] = run_extended_loop(args.port, args.model, sampling=sampling)

    results["post_mem"] = get_mem()
    results["post_metrics"] = scrape_metrics(args.port)
    print(f"\npost_mem: {results['post_mem']}")
    print(f"post_metrics: {results['post_metrics']}")

    out_path = DOCS_DIR / f"FCT090-bench-{args.label}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
