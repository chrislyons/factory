# Factory Port Allocation — Master Reference

**Status:** Living document
**Last updated:** 2026-03-22
**Cross-references:** FCT029 Section 9, WHB001, CLAUDE.md

## Allocation Principles

- 3000-3999, 5000-5999: Project test/build ports (ephemeral, never permanent)
- 4000-4999: Proxy/gateway services
- 6000-6999: Database services
- 8000-8499: Inference + MCP servers
- 8500-8999: Reserved for future MCP
- 11000-11999: Ollama
- 41900-41999: Factory application services

When a service migrates between hosts, it retains its port number.

## Port Tables (by host)

### Cloudkicker (100.86.68.16) — Development Machine

No permanent services. Development-only machine.

### Whitebox (100.88.222.111) — Inference + Database Host

| Port | Service | Protocol | Status |
|------|---------|----------|--------|
| 4000 | LiteLLM proxy | HTTP | Planned |
| 6333 | Qdrant vector DB (HTTP) | HTTP | LIVE |
| 6334 | Qdrant vector DB (gRPC) | gRPC | LIVE |
| 8080 | MLX-LM Nanbeige4.1-3B (Boot + IG-88) | HTTP | Validated |
| 8081 | MLX-LM Qwen3.5-4B (Kelk + Expert) | HTTP | Validated |
| 8082 | MLX-LM LFM2.5-1.2B (Nan) | HTTP | Validated |
| 8083 | MLX-LM Qwen3.5-9B (on-demand reasoning) | HTTP | Validated |
| 11434 | Ollama embeddings | HTTP | LIVE |

### Blackbox (100.87.53.109) — Agent Runtime Host

| Port | Service | Protocol | Status |
|------|---------|----------|--------|
| 6379 | FalkorDB | Redis | LIVE (migrating to Whitebox) |
| 8009 | Pantalaimon (E2EE proxy) | HTTP | LIVE (migrating to Whitebox) |
| 8444 | Graphiti MCP | HTTP | LIVE (migrating to Whitebox) |
| 8445 | matrix-mcp Boot | HTTP | LIVE |
| 8446 | Qdrant MCP | HTTP | LIVE |
| 8447 | Research MCP | HTTP | LIVE |
| 8448 | matrix-mcp Coordinator | HTTP | LIVE |
| 41910 | Portal Caddy (production) | HTTPS | LIVE |
| 41911 | GSD sidecar (jobs.json + status) | HTTP | LIVE |
| 41920-41939 | Preview slots | HTTP | Reserved |
| 41940-41949 | Development servers | HTTP | Reserved |
| 41950-41959 | Coordinator HTTP API | HTTP | Planned |

## Status Key

| Status | Meaning |
|--------|---------|
| LIVE | Running in production |
| Validated | Tested and verified, available on demand |
| Planned | Specified but not yet deployed |
| Reserved | Port range allocated, no specific service assigned |
