#!/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3
"""Persistent HTTP daemon wrapping Hermes AIAgent for a single profile.

Keeps the agent (and its MCP connections) warm across requests, eliminating
the ~5s per-message startup + MCP reinit overhead.  Exposes an OpenAI-compatible
chat completions endpoint consumed by coordinator-rs HermesHttpClient.

Usage: python3 hermes-serve.py --profile ig88 --port 41971"""

import argparse
import asyncio
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

parser = argparse.ArgumentParser(description="Hermes AIAgent HTTP daemon")
parser.add_argument("--profile", required=True, help="Hermes profile name")
parser.add_argument("--port", type=int, required=True, help="Listen port")
_args = parser.parse_args()

profile = _args.profile
port = _args.port
profile_dir = Path.home() / ".hermes" / "profiles" / profile
if not profile_dir.is_dir():
    sys.exit(f"Profile directory not found: {profile_dir}")

os.environ["HERMES_HOME"] = str(profile_dir)
os.environ["HERMES_YOLO_MODE"] = "1"

import yaml  # noqa: E402
from aiohttp import web  # noqa: E402
from run_agent import AIAgent  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [hermes-serve/{profile}] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hermes-serve")

_agent: AIAgent | None = None
_agent_lock = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1)
_start_time = time.monotonic()


def _load_config() -> dict:
    config_path = profile_dir / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _create_agent(config: dict) -> AIAgent:
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "not-needed"
    # max_tokens: profile top-level or agent.max_tokens override. None means
    # hermes-agent library default, which for custom/mlx providers means the
    # request omits max_tokens entirely and mlx-vlm falls back to DEFAULT_MAX_TOKENS=256.
    # Set a generous value in the profile to avoid truncation. See FCT057.
    max_tokens = config.get("max_tokens") or config.get("agent", {}).get("max_tokens")
    # provider: MUST be passed explicitly from profile config. Without this,
    # AIAgent's provider field defaults to "" and runtime_provider.py's routing
    # gate at runtime_provider.py:345-349 fails to match the (requested=custom,
    # cfg=custom) branch even when the profile pins provider: custom. The
    # request then falls through to the OpenRouter path, which sends the local
    # model filesystem path as a model ID and gets HTTP 400. See FCT055 RC-1.
    provider = config.get("provider")
    agent = AIAgent(
        model=config["model"],
        provider=provider,
        base_url=config.get("base_url", ""),
        api_key=api_key,
        enabled_toolsets=config.get("toolsets", []),
        quiet_mode=True,
        max_iterations=config.get("agent", {}).get("max_turns", 90),
        max_tokens=max_tokens,
        ephemeral_system_prompt=None,
        session_id=f"daemon_{profile}_{int(time.time())}",
        platform="tool",
    )
    log.info("AIAgent created — model=%s, provider=%s, toolsets=%s, max_tokens=%s", config["model"], provider, config.get("toolsets", []), max_tokens)
    return agent


def _init_agent() -> None:
    global _agent
    config = _load_config()
    _agent = _create_agent(config)


async def handle_health(_request: web.Request) -> web.Response:
    model = _agent.model if _agent else "unknown"
    return web.json_response({
        "status": "ok",
        "profile": profile,
        "model": model,
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    })


async def handle_chat(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
            status=400,
        )

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return web.json_response(
            {"error": {"message": "Missing or invalid 'messages' array", "type": "invalid_request_error"}},
            status=400,
        )

    system_msg = None
    history = []
    last_user_msg = None

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_msg = content
        elif role == "user":
            if last_user_msg is not None:
                history.append({"role": "user", "content": last_user_msg})
            last_user_msg = content
        elif role == "assistant":
            history.append({"role": "assistant", "content": content})

    if last_user_msg is None:
        return web.json_response(
            {"error": {"message": "No user message found in messages array", "type": "invalid_request_error"}},
            status=400,
        )

    log.info("Request: user_msg=%d chars, history=%d msgs", len(last_user_msg), len(history))
    t0 = time.monotonic()

    async with _agent_lock:
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                _executor,
                lambda: _agent.run_conversation(
                    user_message=last_user_msg,
                    system_message=system_msg,
                    conversation_history=history if history else None,
                ),
            )
        except Exception as exc:
            log.exception("run_conversation failed")
            return web.json_response(
                {"error": {"message": str(exc), "type": "server_error"}},
                status=500,
            )

    elapsed = time.monotonic() - t0
    final = result.get("final_response") or ""
    prompt_tokens = result.get("prompt_tokens", 0)
    completion_tokens = result.get("completion_tokens", 0)
    total_tokens = result.get("total_tokens", 0)

    log.info("Response: %d chars, %d tokens, %.1fs", len(final), total_tokens, elapsed)

    return web.json_response({
        "choices": [{"message": {"content": final}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    })


async def handle_reload(_request: web.Request) -> web.Response:
    log.info("Reloading agent from disk config...")
    async with _agent_lock:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(_executor, _init_agent)
        except Exception as exc:
            log.exception("Reload failed")
            return web.json_response(
                {"error": {"message": str(exc), "type": "server_error"}},
                status=500,
            )
    log.info("Reload complete — model=%s", _agent.model)
    return web.json_response({"status": "reloaded", "model": _agent.model})


def main() -> None:
    log.info("Starting hermes-serve for profile=%s on port=%d", profile, port)
    _init_agent()

    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/v1/chat/completions", handle_chat)
    app.router.add_post("/v1/reload", handle_reload)

    log.info("Listening on http://127.0.0.1:%d", port)
    web.run_app(app, host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    main()
