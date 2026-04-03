#!/usr/bin/env bash
# agent-console.sh — Manage tmux sessions for Factory agents.
#
# Usage:
#   agent-console.sh <agent>            Create/reuse session, print attach command
#   agent-console.sh <agent> --attach   Attach read-write
#   agent-console.sh <agent> --watch    Attach read-only
#   agent-console.sh --list             List all agent-* tmux sessions
#
# Designed to be called from any Tailnet SSH session:
#   ssh nesbitt@whitebox agent-console boot --attach

set -euo pipefail

SOCKET_DIR="/tmp/tmux-nesbitt"
PROG="$(basename "$0")"

usage() {
    cat <<EOF
Usage:
  $PROG <agent>            Create or reuse tmux session, print attach command
  $PROG <agent> --attach   Attach to session (read-write)
  $PROG <agent> --watch    Attach to session (read-only)
  $PROG --list             List all agent-* tmux sessions with status
EOF
    exit 1
}

# Ensure the socket directory exists with correct permissions.
ensure_socket_dir() {
    mkdir -p "$SOCKET_DIR"
    chmod 700 "$SOCKET_DIR"
}

# List all agent-* tmux sessions across known sockets.
list_sessions() {
    ensure_socket_dir
    local found=0
    for sock in "$SOCKET_DIR"/agent-*; do
        [ -e "$sock" ] || continue
        local name
        name="$(basename "$sock")"
        if tmux -L "$name" list-sessions -F "#{session_name}: #{session_windows} window(s), created #{session_created_string}" 2>/dev/null; then
            found=1
        fi
    done
    if [ "$found" -eq 0 ]; then
        echo "No active agent sessions."
    fi
}

# Create a new tmux session with Factory defaults.
create_session() {
    local agent="$1"
    local session="agent-${agent}"

    ensure_socket_dir

    tmux -L "$session" new-session -d -s "$session"

    # Apply session settings.
    tmux -L "$session" set-option -g history-limit 250000
    tmux -L "$session" set-option -g mouse on
    tmux -L "$session" set-option -g window-size largest
    tmux -L "$session" set-option -g destroy-unattached off

    # Status bar: agent name + hostname.
    tmux -L "$session" set-option -g status-left "[${agent}@#{host}] "
    tmux -L "$session" set-option -g status-left-length 40
}

# Check whether a session already exists on its named socket.
session_exists() {
    local session="$1"
    tmux -L "$session" has-session -t "$session" 2>/dev/null
}

# --- Main ---

[ $# -lt 1 ] && usage

# Handle --list before agent-name parsing.
if [ "$1" = "--list" ]; then
    list_sessions
    exit 0
fi

AGENT="$1"
ACTION="${2:-}"
SESSION="agent-${AGENT}"

ensure_socket_dir

# Create session if it does not already exist (idempotent).
if ! session_exists "$SESSION"; then
    create_session "$AGENT"
    echo "Created tmux session: $SESSION (socket: $SOCKET_DIR/$SESSION)"
else
    echo "Reusing existing session: $SESSION"
fi

case "$ACTION" in
    --attach)
        exec tmux -L "$SESSION" attach-session -t "$SESSION"
        ;;
    --watch)
        exec tmux -L "$SESSION" attach-session -t "$SESSION" -r
        ;;
    "")
        echo "Attach with:  tmux -L $SESSION attach-session -t $SESSION"
        echo "Watch with:   tmux -L $SESSION attach-session -t $SESSION -r"
        ;;
    *)
        echo "Unknown option: $ACTION" >&2
        usage
        ;;
esac
