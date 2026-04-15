# FCT067 SSD Expert Streaming, E2EE Migration, and Gemma Tool Call Parser Fix

**Date:** 2026-04-12 to 2026-04-14
**Session:** Multi-day sprint, Whitebox (Mac Studio M1 Max, 32GB)
**Scope:** MLX inference topology, E2EE migration, parser bugfix, security incident response, document recovery
**Agents Affected:** Boot, Kelk, IG-88

---

## Summary

A dense three-day sprint that restructured the entire local inference stack, retired the Pantalaimon E2EE proxy, and traced a persistent tool-call truncation bug to its actual root cause in the Gemma 4 parser. The headline addition is flash-moe SSD expert streaming, which enables the 26B-A4B model to run on 32GB hardware by paging expert weights from NVMe on demand, freeing enough RAM for two concurrent E4B instances. A security incident involving an accidental API key leak to Nous Research was detected, contained, and remediated within the same window.

---

## 1. Gemma 4 write_file Truncation -- Root Cause and Fix

### Symptom

Kelk's `write_file` tool calls were truncated to approximately 100-160 characters, representing a 98% truncation rate on file content. The bug manifested as syntactically valid but severely incomplete tool call arguments.

### Investigation Timeline

**Initial hypothesis:** Premature EOS token generation in the E4B model. A LoRA fine-tuning run was attempted to bias the model away from early stopping during tool call generation.

**LoRA was a red herring.** Inspection of raw model output confirmed the model was generating complete, well-formed content the entire time. The truncation occurred downstream in the parser.

### Actual Root Cause

`mlx_vlm/tool_parsers/gemma4.py` only understood `<|"|>` escape sequences (Gemma's special quote tokens) when parsing tool call arguments. Plain double-quoted strings -- which the model frequently emitted for `write_file` content -- were not handled. Commas appearing inside plain-quoted string values were misinterpreted as argument delimiters, splitting the content at the first interior comma.

### Parser Fix (vendor/mlx-vlm)

Three functions in `gemma4.py` were updated:

- **`_find_matching_brace`** -- Now tracks whether the scan position is inside a plain `"..."` string, respecting backslash escapes. Braces inside quoted strings are no longer treated as structural delimiters.
- **`_split_top_level`** -- Same quoting-awareness added to the comma-splitting logic. Commas inside quoted strings are preserved as literal content.
- **`_parse_value`** -- Added a new code path for plain double-quoted strings with backslash escape handling. The existing `<|"|>` escape path was also fixed to decode JSON escape sequences (`\n` to real newlines, `\t` to tabs, etc.).

### Additional Fixes

- **`ChatRequest` Pydantic model in `server.py`** was missing a `tools` field. Hermes was sending tool definitions in the request body, but the Pydantic model silently dropped them. Added `tools: Optional[List[dict]]` to the model.
- **Adapter cache eviction** in `server.py` -- When a request omitted the adapter field, the server would evict the preloaded adapter and run base weights only. Fixed to default to the preloaded adapter when the request field is absent.

---

## 2. SSD Expert Streaming -- 26B-A4B on 32GB via flash-moe

### Problem

Gemma 4 27B-A4B at 6-bit quantization requires approximately 20GB of RAM. With two E4B instances running for Boot and Kelk (~2.5GB each), the 26B model cannot fit in 32GB alongside macOS overhead. The MLX framework deliberately rejects mmap-based offloading or partial model loading -- Apple's position is that users should purchase hardware with sufficient unified memory [1].

### Research

Apple's "LLM in a Flash" paper [1] demonstrated that large language models can run on devices with limited DRAM by storing weights on flash storage and selectively loading them using a sliding window and row-column bundling strategy. Several open-source implementations exist:

- **mlx-flash** -- Python package, early stage, limited model support
- **SwiftLM** -- Swift implementation targeting iOS/macOS
- **flash-moe** -- Rust implementation specifically targeting MoE architectures [2]

### Solution: flash-moe

flash-moe (MIT licensed) splits MoE models into resident shared weights and per-layer expert chunk bank (ECB) files. At inference time, only the active experts for each token are loaded from SSD via `mmap` + `pread`.

**Architecture:**
- Resident weights: ~2.88GB (attention layers, embeddings, layer norms)
- Expert ECB files: 30 layers x 618MB per layer (stored on NVMe)
- 8 active experts loaded per layer per token
- Total resident RAM: ~3GB (leaves ~29GB for E4B instances + macOS)

**Performance:** 5.4 tok/s sustained on M1 Max at 6-bit quantization. Acceptable for auxiliary tasks (compression, session search, skills hub, vision, web extraction, approval, MCP, memory flush) where latency tolerance is higher.

**Split model location:** `/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit-split/`

**HTTP wrapper:** `scripts/flash-moe-server.py` serves an OpenAI-compatible `/v1/chat/completions` endpoint on port `:41966`.

**Plist:** `com.bootindustries.flash-moe-26b.plist` (RunAtLoad + KeepAlive).

---

## 3. Inference Topology (Post-Sprint)

| Port | Model | Backend | Role | Throughput |
|------|-------|---------|------|------------|
| :41961 | E4B 6-bit | mlx-vlm | Boot main chat | ~30 tok/s |
| :41962 | E4B 6-bit | mlx-vlm | Kelk main chat | ~30 tok/s |
| :41966 | 26B-A4B 6-bit | flash-moe SSD streaming | Shared aux | ~5.4 tok/s |

Boot and Kelk auxiliary slots (compression, session_search, skills_hub, vision, web_extract, approval, mcp, flush_memories) route to `:41966`. Main chat slots remain on dedicated E4B instances for interactive responsiveness.

---

## 4. Nous Research Provider -- IG-88 Only

Nous Portal was added as a cloud inference provider, exclusively for IG-88 (free Mimo Pro inference tier).

- **Provider name:** `nous-mimo` in `custom_providers`, `nous` in built-in provider list
- **API key:** `NOUS_MIMO_IG88_KEY` stored in Infisical under the ig88 project
- **Boot and Kelk are explicitly blocked** from cloud providers. All cloud API keys are scrubbed in their wrapper scripts (`hermes-boot.sh`, `hermes-kelk.sh`)
- `NOUS_MIMO_FACTORY_KEY` was deleted from Infisical after a data leak incident (see Security Incidents below)

---

## 5. Native E2EE Migration (Pantalaimon Retired)

All three agents were migrated from the Pantalaimon E2EE proxy (`localhost:41200`) to direct `matrix.org` connections with native end-to-end encryption via `matrix-nio[e2e]`.

### Build Chain

`python-olm` required a patched build process. CMake 4.3 ships a breaking change that affected libolm's bundled CMake configuration. A cmake wrapper script was created that bypasses the bundled libolm build and links against Homebrew's `libolm` installation instead.

`matrix-nio[e2e]` extras were installed into the Hermes virtualenv after `python-olm` was available.

### Cross-Signing Updates

`scripts/matrix-cross-sign/cross-sign.ts` was updated:

- Added `--user` flag for per-bot operation (previously operated on all bots in sequence)
- Removed Pantalaimon integration code paths
- Credentials are now passed via short-lived subshell environment variables only -- never persisted to disk or environment files

### Credential Management

- Recovery keys and passwords remain in the personal password vault (not in Infisical)
- Infisical cleanup: `MATRIX_TOKEN_PAN_*` entries deprecated, `MATRIX_RECOVERY_*` entries removed from the factory project
- Only `MATRIX_TOKEN_{BOOT,IG88,KELK}` remain in Infisical as runtime access tokens

---

## 6. mlx-vlm Patches (vendor/mlx-vlm)

| File | Change |
|------|--------|
| `server.py` | Added `tools: Optional[List[dict]]` to `ChatRequest` Pydantic model |
| `server.py` | Adapter cache eviction fix -- default to preloaded adapter when request omits field |
| `tool_parsers/gemma4.py` | Plain double-quote string handling in brace matching, comma splitting, and value parsing |
| `trainer/lora.py` | 6-bit quantization dimension fix (integer division truncation on non-divisible dimensions) |
| `trainer/utils.py` | kwargs filter for `get_peft_model` to prevent unexpected keyword argument errors |

---

## 7. Kelk Document Recovery

18 files were recovered from truncated Hermes session transcripts. The truncation was caused by the parser bug documented in Section 1 -- `write_file` calls during Kelk's autonomous document creation sessions had been silently truncated.

- `graph_data` nodes restored to full content (e.g., `Matt.md`: 560 to 2782 bytes)
- `docs/` directory restructured: `foundation/` moved from `klk/` to `docs/` root
- `CLAUDE.md` and `SOUL.md` paths updated to reflect new directory structure

---

## 8. Global Config Hardening

- `~/.hermes/config.yaml` global default model reset to local E4B (had been accidentally set to Nous Mimo Pro, causing the data leak)
- Nous auth credentials removed from global `auth.json`
- Boot and Kelk profiles: zero cloud provider references remain
- Boot and Kelk wrapper scripts: `unset NOUS_MIMO_FACTORY_KEY` added to the environment scrub block

---

## Security Incidents

### Nous API Key Leak

**Vector:** A user-pasted curl example in a conversation thread contained the `NOUS_MIMO_FACTORY_KEY` in plaintext. The key was rotated immediately upon detection.

### Kelk Personal Data Exposure

**Vector:** Kelk sent personal data to the Nous/Mimo Pro cloud inference endpoint. Root cause was the global Hermes config (`~/.hermes/config.yaml`) having `nous` set as the default provider. When Kelk's profile-specific local provider was unavailable or the routing fell through, it auto-fell back to the global default -- which was a cloud endpoint.

**Remediation:**
1. Removed `nous` from global config, profiles, and auth stores
2. Deleted `NOUS_MIMO_FACTORY_KEY` from Infisical
3. Added explicit `unset` directives in Boot and Kelk wrapper scripts
4. Verified Boot and Kelk profiles contain zero cloud provider references

---

## Files Modified

- `~/.hermes/config.yaml` (global)
- `~/.hermes/profiles/{boot,kelk,ig88}/config.yaml`
- `~/.hermes/profiles/ig88/auth.json`
- `~/.hermes/auth.json`
- `~/dev/vendor/mlx-vlm/mlx_vlm/server.py`
- `~/dev/vendor/mlx-vlm/mlx_vlm/tool_parsers/gemma4.py`
- `~/dev/vendor/mlx-vlm/mlx_vlm/trainer/lora.py`
- `~/dev/vendor/mlx-vlm/mlx_vlm/trainer/utils.py`
- `~/dev/factory/scripts/hermes-{boot,kelk,ig88}.sh`
- `~/dev/factory/scripts/matrix-cross-sign/cross-sign.ts`
- `~/dev/factory/plists/com.bootindustries.{mlx-vlm-boot,mlx-vlm-kelk,flash-moe-26b,mlx-flash-26b}.plist`
- `~/dev/factory/agents/kelk/docs/` (restructured)
- `~/dev/factory/agents/kelk/CLAUDE.md`
- `~/.hermes/profiles/kelk/SOUL.md`

## Files Created

- `~/dev/vendor/flash-moe-gemma4/` (cloned from philtrem/qwen3.5-gemma4-moe-flash-mlx-turbo-quant)
- `/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit-split/` (flash-moe split model)
- `~/dev/factory/scripts/flash-moe-server.py`
- `~/dev/factory/plists/com.bootindustries.flash-moe-26b.plist`

---

## References

[1] A. Alizadeh et al., "LLM in a Flash: Efficient Large Language Model Inference with Limited Memory," arXiv:2312.11514, Dec. 2023.

[2] philtrem, "flash-moe: SSD expert streaming for MoE models on Apple Silicon," GitHub, 2026. [Online]. Available: https://github.com/philtrem/qwen3.5-gemma4-moe-flash-mlx-turbo-quant
