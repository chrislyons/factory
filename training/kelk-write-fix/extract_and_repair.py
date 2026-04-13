#!/usr/bin/env python3
"""
Extract write_file calls from Kelk Hermes sessions.
Tool calls are in msg['tool_calls'][].function.{name, arguments}
"""
import json, os
from pathlib import Path

SESSIONS_DIR = Path(os.path.expanduser("~/.hermes/profiles/kelk/sessions"))
OUTPUT = Path("training/kelk-write-fix/raw_extracts.jsonl")

def extract_write_calls(session_path):
    try:
        with open(session_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    messages = data.get("messages", data.get("history", []))
    results = []

    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue

        tool_calls = msg.get("tool_calls", [])
        if not tool_calls:
            continue

        # Get planning text from content
        plan_text = msg.get("content", "")
        if isinstance(plan_text, list):
            plan_text = " ".join(b.get("text","") for b in plan_text if isinstance(b,dict) and b.get("type")=="text")

        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            if name not in ("write_file", "patch"):
                continue

            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {"raw": args_str}

            file_content = args.get("content", "")
            file_path = args.get("path", args.get("file_path", ""))

            if not file_content and not file_path:
                continue

            # Clean escaped quotes from content
            if isinstance(file_content, str) and file_content.startswith('"'):
                try:
                    file_content = json.loads(file_content)
                except:
                    pass

            # Measure body
            body = file_content
            if "---" in file_content and file_content.startswith('"---') or file_content.startswith('---'):
                parts = file_content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2].strip()

            word_count = len(body.split()) if body else 0
            likely_truncated = word_count < 80

            results.append({
                "session": session_path.name,
                "file_path": file_path,
                "plan_text": plan_text[:2000] if plan_text else "",
                "written_content": file_content[:5000],
                "written_word_count": word_count,
                "likely_truncated": likely_truncated,
            })

    return results

def main():
    all_extracts = []
    session_files = sorted(SESSIONS_DIR.glob("session_*.json"))
    print(f"Scanning {len(session_files)} Kelk sessions...")

    for sf in session_files:
        extracts = extract_write_calls(sf)
        all_extracts.extend(extracts)

    truncated = [e for e in all_extracts if e["likely_truncated"]]
    complete = [e for e in all_extracts if not e["likely_truncated"]]

    print(f"Total write_file calls found: {len(all_extracts)}")
    print(f"  Complete (>=80 words body): {len(complete)}")
    print(f"  Likely truncated (<80 words body): {len(truncated)}")

    with open(OUTPUT, "w") as f:
        for e in all_extracts:
            f.write(json.dumps(e) + "\n")
    print(f"Written to {OUTPUT}")

    if truncated:
        print(f"\n--- Sample truncated writes ---")
        for t in truncated[:5]:
            print(f"\nFile: {t['file_path']}")
            print(f"Words: {t['written_word_count']}")
            print(f"Content preview: {t['written_content'][:200]}...")
            print()

if __name__ == "__main__":
    main()
