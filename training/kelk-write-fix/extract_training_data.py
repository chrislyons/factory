#!/usr/bin/env python3
"""
Extract tool-call errors from Hermes agent sessions and generate corrected
training examples for E4B LoRA fine-tuning.

Categories:
  1. patch errors (Boot) — old_string not unique or not found
  2. patch errors (Kelk) — same as above
  3. syntax errors (IG-88) — SyntaxError in execute_code/terminal
  4. path errors (IG-88) — FileNotFoundError / No such file in write_file/read_file/terminal

Output: one JSONL file per category in chat-format training examples.
"""
import json
import os
import glob
from pathlib import Path
from typing import Any

HERMES_ROOT = Path(os.path.expanduser("~/.hermes/profiles"))
OUTPUT_DIR = Path("/Users/nesbitt/dev/factory/training/kelk-write-fix")

# ─── Helpers ───────────────────────────────────────────────────────────

def load_session(path: str) -> list[dict]:
    """Load messages from a Hermes session dump."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("request", {}).get("body", {}).get("messages", [])
    except (json.JSONDecodeError, IOError):
        return []


def find_tool_call(msgs: list[dict], tool_result_idx: int, tool_call_id: str):
    """Walk backward from a tool result to find the matching assistant tool_call."""
    for j in range(tool_result_idx - 1, -1, -1):
        for tc in msgs[j].get("tool_calls", []):
            if tc.get("id") == tool_call_id:
                return j, tc, msgs[j].get("content", "") or ""
    return None, None, ""


def find_user_msg(msgs: list[dict], before_idx: int) -> str:
    """Find the most recent user message before a given index."""
    for k in range(before_idx - 1, -1, -1):
        if msgs[k].get("role") == "user":
            return str(msgs[k].get("content", ""))[:1000]
    return ""


def parse_tool_args(tc: dict) -> dict:
    """Parse tool call arguments, handling both str and dict forms."""
    args_raw = tc.get("function", {}).get("arguments", "{}")
    if isinstance(args_raw, str):
        try:
            return json.loads(args_raw), args_raw
        except json.JSONDecodeError:
            return {"_raw": args_raw}, args_raw
    return args_raw, json.dumps(args_raw)


def make_training_example(
    user_msg: str,
    assistant_text: str,
    tool_name: str,
    corrected_args: dict,
    tool_result: str,
    category: str,
) -> dict:
    """Build a single chat-format training example."""
    messages = []
    if user_msg:
        messages.append({"role": "user", "content": user_msg})

    asst_msg: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_text if assistant_text else None,
        "tool_calls": [
            {
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(corrected_args, ensure_ascii=False),
                }
            }
        ],
    }
    messages.append(asst_msg)
    messages.append({"role": "tool", "content": tool_result})
    return {"messages": messages, "category": category}


# ─── Category 1 & 2: Patch errors (Boot + Kelk) ───────────────────────

def extract_patch_errors(profile: str) -> list[dict]:
    """Find patch tool calls that failed (success: false)."""
    session_dir = HERMES_ROOT / profile / "sessions"
    files = sorted(glob.glob(str(session_dir / "*.json")))
    examples = []

    # Read the target file for generating corrections
    config_cache: dict[str, list[str]] = {}

    for fpath in files:
        msgs = load_session(fpath)
        for i, m in enumerate(msgs):
            if m.get("role") != "tool":
                continue
            content = str(m.get("content", ""))
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                continue
            if result.get("success") is not False:
                continue

            tid = m.get("tool_call_id", "")
            asst_idx, tc, asst_text = find_tool_call(msgs, i, tid)
            if not tc or tc["function"]["name"] != "patch":
                continue

            args, args_raw = parse_tool_args(tc)
            user_msg = find_user_msg(msgs, asst_idx or i)
            target_path = args.get("path", "")
            old_string = args.get("old_string", "")
            new_string = args.get("new_string", "")
            error_msg = result.get("error", "")

            # Generate corrected version
            corrected_args = dict(args)

            # The old_string/new_string come from JSON-parsed tool args,
            # so they represent the literal text the model intended to match.
            clean_old = old_string
            clean_new = new_string

            # Load target file for corrections
            if target_path and target_path not in config_cache:
                try:
                    with open(target_path) as tf:
                        config_cache[target_path] = tf.readlines()
                except (IOError, OSError):
                    config_cache[target_path] = []
            file_lines = config_cache.get(target_path, [])

            if "2 matches" in error_msg or "multiple matches" in error_msg.lower():
                # Need more context — find first match and add surrounding lines
                if file_lines:
                    # Try exact match first, then fuzzy (the port may have changed since)
                    search_variants = [clean_old.strip()]
                    # Also try with any port number replaced
                    import re
                    generic = re.sub(r':\d{5}/', ':XXXXX/', clean_old.strip())
                    if generic != clean_old.strip():
                        search_variants.append(generic)

                    for li, line in enumerate(file_lines):
                        matched = any(sv in line for sv in search_variants)
                        if not matched and generic != clean_old.strip():
                            matched = re.sub(r':\d{5}/', ':XXXXX/', line.strip()) == generic
                        if matched:
                            # Grab 3 lines before for unique context
                            start = max(0, li - 3)
                            context_block = "".join(file_lines[start : li + 1]).rstrip("\n")
                            replacement_block = (
                                "".join(file_lines[start:li])
                                + clean_new + "\n"
                            ).rstrip("\n")
                            corrected_args["old_string"] = context_block
                            corrected_args["new_string"] = replacement_block
                            break

            elif "not found" in error_msg.lower() or "could not find" in error_msg.lower():
                # old_string doesn't match — find the actual line in the file
                if file_lines:
                    search_key = clean_old.strip()
                    for li, line in enumerate(file_lines):
                        if search_key in line.rstrip("\n") or (
                            len(search_key) > 10 and search_key[10:40] in line
                        ):
                            # Add surrounding context to make unique
                            start = max(0, li - 3)
                            context_block = "".join(file_lines[start : li + 1]).rstrip("\n")
                            replacement_block = (
                                "".join(file_lines[start:li])
                                + clean_new + "\n"
                            ).rstrip("\n")
                            corrected_args["old_string"] = context_block
                            corrected_args["new_string"] = replacement_block
                            break

            # Build training example with the correction
            example = make_training_example(
                user_msg=user_msg,
                assistant_text=str(asst_text)[:500],
                tool_name="patch",
                corrected_args=corrected_args,
                tool_result='{"success": true}',
                category="patch",
            )
            example["_original_error"] = error_msg
            example["_source_file"] = os.path.basename(fpath)
            examples.append(example)

    return examples


# ─── Category 3: Python syntax errors (IG-88) ─────────────────────────

def extract_syntax_errors() -> list[dict]:
    """Find execute_code / terminal calls with SyntaxError."""
    session_dir = HERMES_ROOT / "ig88" / "sessions"
    files = sorted(glob.glob(str(session_dir / "*.json")))
    examples = []

    for fpath in files:
        msgs = load_session(fpath)
        for i, m in enumerate(msgs):
            if m.get("role") != "tool":
                continue
            content = str(m.get("content", ""))
            if "SyntaxError" not in content:
                continue

            tid = m.get("tool_call_id", "")
            asst_idx, tc, asst_text = find_tool_call(msgs, i, tid)
            if not tc:
                continue

            tool_name = tc["function"]["name"]
            args, args_raw = parse_tool_args(tc)
            user_msg = find_user_msg(msgs, asst_idx or i)

            # Extract the broken code
            if tool_name == "execute_code":
                broken_code = args.get("code", "")
            elif tool_name == "terminal":
                broken_code = args.get("command", "")
            else:
                continue

            # Fix common issues
            fixed_code = broken_code
            # Fix escaped triple-quotes: \\\"\\\"\\\" → """
            fixed_code = fixed_code.replace('\\"\\"\\"', '"""')
            fixed_code = fixed_code.replace('\\\"\\\"\\"', '"""')
            # Fix << instead of <
            # (only when it looks like a comparison, not a bitshift)
            import re
            fixed_code = re.sub(r'(\w+)\s*<<\s*(\d)', r'\1 < \2', fixed_code)
            # Fix self self
            fixed_code = re.sub(r'\bself\s+self\b', 'self', fixed_code)

            corrected_args = dict(args)
            if tool_name == "execute_code":
                corrected_args["code"] = fixed_code
            else:
                corrected_args["command"] = fixed_code

            example = make_training_example(
                user_msg=user_msg,
                assistant_text=str(asst_text)[:500],
                tool_name=tool_name,
                corrected_args=corrected_args,
                tool_result='{"status": "success", "output": "OK"}',
                category="syntax",
            )
            example["_original_error"] = content[:300]
            example["_source_file"] = os.path.basename(fpath)
            examples.append(example)

    return examples


# ─── Category 4: File path errors (IG-88) ─────────────────────────────

def extract_path_errors() -> list[dict]:
    """Find read_file/write_file/terminal calls with path errors."""
    session_dir = HERMES_ROOT / "ig88" / "sessions"
    files = sorted(glob.glob(str(session_dir / "*.json")))
    examples = []

    for fpath in files:
        msgs = load_session(fpath)
        for i, m in enumerate(msgs):
            if m.get("role") != "tool":
                continue
            content = str(m.get("content", ""))

            is_path_error = False
            try:
                result = json.loads(content)
                err_str = str(result.get("error", "")) + result.get("output", "")
                if "No such file" in err_str or "FileNotFoundError" in err_str:
                    is_path_error = True
            except json.JSONDecodeError:
                if "No such file" in content or "FileNotFoundError" in content:
                    is_path_error = True

            if not is_path_error:
                continue

            tid = m.get("tool_call_id", "")
            asst_idx, tc, asst_text = find_tool_call(msgs, i, tid)
            if not tc:
                continue

            tool_name = tc["function"]["name"]
            args, args_raw = parse_tool_args(tc)
            user_msg = find_user_msg(msgs, asst_idx or i)

            # Determine wrong path and try to find the correct one
            wrong_path = ""
            corrected_args = dict(args)

            if tool_name in ("read_file", "write_file"):
                wrong_path = args.get("path", "")

                # Check for empty/missing path (malformed args)
                if not wrong_path:
                    # The args JSON was corrupted — content leaked into keys
                    # Reconstruct: find "path" key buried in the dict
                    for k, v in args.items():
                        if k == '"path"' or k == "path":
                            wrong_path = v
                            break
                    if not wrong_path and "content" in args:
                        # Try to infer path from content
                        content_str = str(args.get("content", ""))
                        if "IG88" in content_str:
                            # Extract doc number from content
                            import re
                            match = re.search(r"IG88(\d+)", content_str)
                            if match:
                                doc_num = match.group(0)
                                wrong_path = f"/Users/nesbitt/dev/factory/agents/ig88/docs/ig88/{doc_num}.md"

                    if wrong_path:
                        corrected_args = {
                            "path": wrong_path,
                            "content": str(args.get("content", ""))[:3000],
                        }

                # Try to find the correct path
                if wrong_path:
                    parent = os.path.dirname(wrong_path)
                    basename = os.path.basename(wrong_path)
                    if os.path.isdir(parent):
                        # Check if file exists with different name
                        existing = os.listdir(parent)
                        # Look for similar files
                        for ef in existing:
                            if basename.lower().replace("-", "").replace("_", "") in ef.lower().replace("-", "").replace("_", ""):
                                corrected_args["path"] = os.path.join(parent, ef)
                                break
                    elif not os.path.isdir(parent):
                        # Parent dir doesn't exist — check nearby
                        grandparent = os.path.dirname(parent)
                        if os.path.isdir(grandparent):
                            corrected_args["path"] = wrong_path  # path itself is OK, dir needs mkdir

            elif tool_name == "terminal":
                cmd = args.get("command", "")
                # Extract path from command
                import re
                path_match = re.search(r"python3\s+(\S+)", cmd)
                if path_match:
                    wrong_path = path_match.group(1)
                    # Check if it exists
                    if not os.path.isabs(wrong_path):
                        wrong_path = os.path.join(
                            "/Users/nesbitt/dev/factory/agents/ig88", wrong_path
                        )
                    parent = os.path.dirname(wrong_path)
                    if os.path.isdir(parent):
                        existing = os.listdir(parent)
                        basename = os.path.basename(wrong_path)
                        for ef in existing:
                            if ef.startswith(basename[:10]):
                                corrected_path = os.path.join(parent, ef)
                                corrected_args["command"] = cmd.replace(
                                    path_match.group(1), corrected_path
                                )
                                break

            example = make_training_example(
                user_msg=user_msg,
                assistant_text=str(asst_text)[:500],
                tool_name=tool_name,
                corrected_args=corrected_args,
                tool_result='{"success": true}',
                category="paths",
            )
            example["_wrong_path"] = wrong_path
            example["_original_error"] = content[:300]
            example["_source_file"] = os.path.basename(fpath)
            examples.append(example)

    return examples


# ─── Main ──────────────────────────────────────────────────────────────

def write_jsonl(examples: list[dict], filename: str):
    """Write examples to JSONL file."""
    outpath = OUTPUT_DIR / filename
    with open(outpath, "w") as f:
        for ex in examples:
            # Remove internal metadata before writing
            clean = {k: v for k, v in ex.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return outpath


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Task 1: skill_manage — No skill_manage tool calls found in boot/kelk sessions.
    # The Hermes tool set uses different names. Writing empty file with note.
    skill_manage_examples: list[dict] = []
    print(f"[skill_manage] No skill_manage tool found in boot/kelk sessions (tool not available in Hermes E4B profiles)")
    write_jsonl(skill_manage_examples, "repaired_skill_manage.jsonl")

    # Task 2: patch errors (Boot + Kelk)
    patch_examples = []
    for profile in ["boot", "kelk"]:
        errs = extract_patch_errors(profile)
        patch_examples.extend(errs)
        print(f"[patch/{profile}] Extracted {len(errs)} errors")
    outpath = write_jsonl(patch_examples, "repaired_patch.jsonl")
    print(f"  -> {outpath} ({len(patch_examples)} examples)")

    # Task 3: syntax errors (IG-88)
    syntax_examples = extract_syntax_errors()
    print(f"[syntax/ig88] Extracted {len(syntax_examples)} errors")
    outpath = write_jsonl(syntax_examples, "repaired_syntax.jsonl")
    print(f"  -> {outpath} ({len(syntax_examples)} examples)")

    # Task 4: path errors (IG-88)
    path_examples = extract_path_errors()
    print(f"[paths/ig88] Extracted {len(path_examples)} errors")
    outpath = write_jsonl(path_examples, "repaired_paths.jsonl")
    print(f"  -> {outpath} ({len(path_examples)} examples)")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  skill_manage : {len(skill_manage_examples):3d} examples")
    print(f"  patch        : {len(patch_examples):3d} examples")
    print(f"  syntax       : {len(syntax_examples):3d} examples")
    print(f"  paths        : {len(path_examples):3d} examples")
    total = len(skill_manage_examples) + len(patch_examples) + len(syntax_examples) + len(path_examples)
    print(f"  TOTAL        : {total:3d} examples")


if __name__ == "__main__":
    main()
