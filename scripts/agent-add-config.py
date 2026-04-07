#!/usr/bin/env python3
"""Append a new agent block to agent-config.yaml using ruamel.yaml.

Preserves all inline comments and formatting. Uses the Boot entry as
the structural template for new agents.

Usage:
    python3 scripts/agent-add-config.py \
        --name xamm \
        --matrix-user "@xamm:matrix.org" \
        --port 41964 \
        --model /Users/nesbitt/models/Nanbeige4.1-3B-8bit \
        --description "Examiner agent" \
        --config agents/ig88/config/agent-config.yaml
"""
import argparse
import sys

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ERROR: ruamel.yaml not installed.", file=sys.stderr)
    print("  pip3 install ruamel.yaml", file=sys.stderr)
    sys.exit(1)

from ruamel.yaml.comments import CommentedMap


def build_agent_block(name: str, matrix_user: str, port: int,
                      model: str, description: str) -> CommentedMap:
    """Build a new agent CommentedMap modelled on the Boot entry."""
    name_upper = name.upper()
    token_env = f"MATRIX_TOKEN_PAN_{name_upper}"

    # Next available Hermes port — derive from MLX port offset
    # Boot=41961->41970, IG88=41988->41971, Kelk=41962->41972
    # New agents get 41973+ sequentially, but we just use port+9 as a simple heuristic
    # (the Hermes port is informational — coordinator reads hermes_profile name, not port)
    hermes_port = port + 9 if port < 41970 else port + 2

    block = CommentedMap()
    block["matrix_user"] = matrix_user
    block["token_env"] = token_env
    block["description"] = description
    block["sandbox_profile"] = "work"
    block["default_device"] = "whitebox"
    block["default_cwd"] = f"/Users/nesbitt/dev/factory/agents/{name}"
    block["trust_level"] = 2
    block["identity_files"] = CommentedMap({
        "soul": "soul.md",
        "principles": "principles.md",
        "agents": "agents.md",
    })
    block["runtime"] = "hermes"
    block["hermes_profile"] = name
    block["hermes_port"] = hermes_port
    block["scoped_env"] = CommentedMap({
        "OPENAI_API_KEY": "not-needed",
    })
    block["system_prompt"] = (
        f"IDENTITY BOUNDARY — READ FIRST\n"
        f"You are {name.capitalize()}. Other agents in this system: "
        f"Boot (projects/dev), IG-88 (trading/market analysis), Kelk (personal assistant).\n"
        f"If a message is clearly addressed to another agent, stay silent or defer.\n"
        f"Never claim to be, speak as, or impersonate another agent.\n"
        f"In past sessions, agents confused identities in shared rooms — "
        f"this is your highest-priority constraint.\n"
    )
    return block


def main():
    parser = argparse.ArgumentParser(description="Add agent to agent-config.yaml")
    parser.add_argument("--name", required=True, help="Agent name (lowercase)")
    parser.add_argument("--matrix-user", required=True, help="Matrix user ID")
    parser.add_argument("--port", required=True, type=int, help="MLX-LM inference port")
    parser.add_argument("--model", required=True, help="Model path on Whitebox")
    parser.add_argument("--description", default="", help="Agent description")
    parser.add_argument("--config", required=True, help="Path to agent-config.yaml")
    args = parser.parse_args()

    name = args.name.lower()

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 120

    with open(args.config, "r") as f:
        doc = yaml.load(f)

    agents = doc.get("agents")
    if agents is None:
        print("ERROR: No 'agents:' section found in config.", file=sys.stderr)
        sys.exit(1)

    if name in agents:
        print(f"ERROR: Agent '{name}' already exists in config.", file=sys.stderr)
        sys.exit(1)

    block = build_agent_block(
        name=name,
        matrix_user=args.matrix_user,
        port=args.port,
        model=args.model,
        description=args.description or f"{name.capitalize()} agent",
    )

    # Add a comment before the new agent block
    agents[name] = block
    agents.yaml_set_comment_before_after_key(
        name, before=f"\n  {name.capitalize()} — provisioned by agent-add", indent=2
    )

    with open(args.config, "w") as f:
        yaml.dump(doc, f)

    print(f"OK: Added '{name}' to {args.config}")


if __name__ == "__main__":
    main()
