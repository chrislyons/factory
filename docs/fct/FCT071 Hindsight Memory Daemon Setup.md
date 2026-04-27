# FCT071 Hindsight Memory Daemon Setup

**Date:** 2026-04-26
**Author:** Gonzo (infrastructure)
**Status:** Live (awaiting model deployment on :41961)

---

## Summary

Hindsight is a memory daemon that provides persistent, searchable memory for Hermes
agents using a graph-based approach with local embeddings and LLM-powered fact extraction.

- **Port:** 41930 (bind 0.0.0.0)
- **Version:** hindsight-api 0.5.4 (via `uvx`)
- **Database:** pg0 (embedded PostgreSQL, auto-managed)
- **Embeddings:** BAAI/bge-small-en-v1.5 (local, 384-dim)
- **Reranker:** cross-encoder/ms-marco-MiniLM-L-6-v2 (local, MPS)
- **LLM:** Ornstein3.6-35B-A3B-MLX-6bit via local mlx-vlm.server on :41961
- **Bank:** hermes-default

## Architecture

```
Hermes Agent (CLI/gateway)
    |
    | HTTP POST /v1/default/banks/hermes-default/memories
    v
Hindsight API (:41930)
    |
    +-- LLM Extraction: local mlx-vlm.server (:41961)
    |   Ornstein3.6-35B-A3B-MLX-6bit (MoE, mmap, ~5GB resident)
    |   Converts raw text into structured facts/observations
    |
    +-- Local Embeddings: BAAI/bge-small-en-v1.5 (MPS)
    |   384-dim vector embeddings for semantic search
    |
    +-- Local Reranker: ms-marco-MiniLM-L-6-v2
    |   Cross-encoder for recall precision
    |
    +-- pg0: Embedded PostgreSQL
        Stores memories, facts, chunks, graph edges
```

## Sovereignty

Hindsight uses the same local inference server as Boot and Kelk. No data leaves
Whitebox. The LLM extraction happens on-device via mmap-loaded MLX model.

## Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/default/banks/hermes-default/memories` | POST | Retain memories (text items) |
| `/v1/default/banks/hermes-default/memories/recall` | POST | Semantic search over stored memories |
| `/v1/default/banks/hermes-default/memories/list` | GET | List stored facts/observations |
| `/v1/default/banks/hermes-default/stats/memories-timeseries` | GET | Memory count over time |
| `/health` | GET | Health check |
| `/mcp/` | POST | MCP protocol endpoint |

## Launch

### Script
`/Users/nesbitt/dev/factory/scripts/hindsight-start.sh`

Points at local mlx-vlm.server on :41961. No cloud API key needed.

### Launchd
`~/Library/LaunchAgents/com.bootindustries.hindsight-api.plist`

- Label: `com.bootindustries.hindsight-api`
- KeepAlive: true
- RunAtLoad: true
- Logs: `~/Library/Logs/factory/hindsight-api.log`

### Manual start
```bash
bash /Users/nesbitt/dev/factory/scripts/hindsight-start.sh
```

### Register with launchd
```bash
launchctl load ~/Library/LaunchAgents/com.bootindustries.hindsight-api.plist
```

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `HINDSIGHT_API_LLM_PROVIDER` | `openai` | OpenAI-compatible client (mlx-vlm.server) |
| `HINDSIGHT_API_LLM_MODEL` | `Ornstein3.6-35B-A3B-MLX-6bit` | Model served on :41961 |
| `HINDSIGHT_API_LLM_BASE_URL` | `http://127.0.0.1:41961/v1` | Local inference server |
| `HINDSIGHT_API_LLM_API_KEY` | `sk-local-no-auth` | Dummy key (local server doesn't validate) |
| `HINDSIGHT_EMBED_BANK_ID` | `hermes-default` | Default memory bank |

## LLM Provider Configuration

The `openai` provider in hindsight-api uses an AsyncOpenAI client. The local
mlx-vlm.server exposes an OpenAI-compatible `/v1/chat/completions` endpoint.
A dummy API key is required by Hindsight's startup check but is not validated
by the local server.

**Important:** The `openai_compatible` provider string is NOT valid. Use `openai`
with a custom `base_url` pointing to the local server.

## Memory Bank: hermes-default

All memories are stored in the `hermes-default` bank. This is shared across all agents
and profiles. Future work may separate banks per agent.

## Pitfalls

- The `openai_compatible` provider name is rejected as invalid. Use `openai` with
  `HINDSIGHT_API_LLM_BASE_URL` pointing to the local server.
- The `lmstudio` provider is NOT appropriate — it implies LM Studio, not a custom
  OpenAI-compatible server. Use `openai` for local mlx-vlm.server.
- DELETE on `/v1/default/banks/{bank}/memories/{id}` returns 405 Method Not Allowed.
  Duplicate memories from failed retain attempts cannot be deleted via API.
- The recall endpoint is `/memories/recall`, not just `/recall`.
- Hindsight shares :41961 with Boot and Kelk. Extraction requests queue behind
  agent generation. This is acceptable because extraction is async and low-urgency.
- Will improve when vllm-mlx is deployed (continuous batching interleaves requests).
