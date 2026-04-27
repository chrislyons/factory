#!/usr/bin/env python3
"""Update Hermes Boot + Kelk configs for Ornstein3.6-35B-A3B deployment.

Reads existing configs, applies changes, writes back.
Creates .bak files before modifying.

Usage: python3 ~/dev/factory/scripts/update-hermes-configs.py [--dry-run]
"""

import sys
import os
import shutil
import re

DRY_RUN = "--dry-run" in sys.argv

MODEL_PATH = "/Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit"
MODEL_NAME = "Ornstein3.6-35B-A3B-MLX-6bit"
PORT = "41961"

CONFIGS = [
    os.path.expanduser("~/.hermes/profiles/boot/config.yaml"),
    os.path.expanduser("~/.hermes/profiles/kelk/config.yaml"),
]

def update_config(path):
    """Apply all changes to a single config file."""
    with open(path, "r") as f:
        content = f.read()

    original = content

    # 1. Model default: gemma-4-e4b-it-6bit → Ornstein3.6-35B-A3B-MLX-6bit
    content = content.replace(
        "/Users/nesbitt/models/gemma-4-e4b-it-6bit",
        MODEL_PATH
    )

    # 2. All base_url ports → :41961 (catches :41961, :41962, :41966)
    content = re.sub(
        r'http://127\.0\.0\.1:\d+/v1',
        f'http://127.0.0.1:{PORT}/v1',
        content
    )

    # 3. Auxiliary model names: local-26b-a4b → local-ornstein-35b
    content = content.replace(
        "model: local-26b-a4b",
        "model: local-ornstein-35b"
    )

    # 4. Compression summary_model: gemma-4-26b-a4b-it-6bit → Ornstein model
    content = content.replace(
        "summary_model: gemma-4-26b-a4b-it-6bit",
        f"summary_model: {MODEL_NAME}"
    )

    # 5. Providers API: ensure all point to :41961
    content = content.replace(
        "api: http://127.0.0.1:41962/v1",
        f"api: http://127.0.0.1:{PORT}/v1"
    )

    # Count changes
    changes = sum(1 for a, b in zip(original, content) if a != b)

    if content == original:
        print(f"  {path}: no changes needed")
        return

    if DRY_RUN:
        print(f"  {path}: {changes} chars changed (DRY RUN, not writing)")
        # Show diff-like output
        for i, (a, b) in enumerate(zip(original.splitlines(), content.splitlines())):
            if a != b:
                print(f"    L{i+1}: - {a.strip()}")
                print(f"    L{i+1}: + {b.strip()}")
        return

    # Backup
    bak = path + ".bak"
    shutil.copy2(path, bak)
    print(f"  {path}: backed up to {bak}")

    # Write
    with open(path, "w") as f:
        f.write(content)
    print(f"  {path}: updated ({changes} chars changed)")


def main():
    print(f"=== Hermes Config Update ===")
    print(f"Model: {MODEL_PATH}")
    print(f"Port: :{PORT}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print()

    for path in CONFIGS:
        if not os.path.exists(path):
            print(f"  ERROR: {path} not found")
            sys.exit(1)
        update_config(path)

    print()
    print("=== Done ===")
    if not DRY_RUN:
        print("Restart Hermes gateways to pick up changes:")
        print("  launchctl unload ~/Library/LaunchAgents/com.bootindustries.hermes-boot.plist")
        print("  launchctl load ~/Library/LaunchAgents/com.bootindustries.hermes-boot.plist")
        print("  launchctl unload ~/Library/LaunchAgents/com.bootindustries.hermes-kelk.plist")
        print("  launchctl load ~/Library/LaunchAgents/com.bootindustries.hermes-kelk.plist")


if __name__ == "__main__":
    main()
