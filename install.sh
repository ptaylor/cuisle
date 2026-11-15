#!/usr/bin/env bash
# Install the `cuisle` command into a target directory via a symbolic link.
#
# Usage:
#   ./install.sh [TARGET_DIR]
#
# TARGET_DIR defaults to ~/bin. The script is idempotent: re-running it when the
# link already points at this repository's executable is a no-op. It refuses to
# overwrite an unrelated file.

set -euo pipefail

usage() {
    cat >&2 << 'USAGE'
Usage: ./install.sh [TARGET_DIR]

Install the cuisle command into TARGET_DIR via a symbolic link.
TARGET_DIR defaults to ~/bin and should be on your PATH.

Examples:
  ./install.sh
  ./install.sh ~/bin
  ./install.sh /usr/local/bin
USAGE
}

if [ $# -gt 1 ]; then
    echo "Error: at most one TARGET_DIR is accepted." >&2
    usage
    exit 1
fi

TARGET_DIR="${1:-$HOME/bin}"
if [ -e "$TARGET_DIR" ] && [ ! -d "$TARGET_DIR" ]; then
    echo "Error: '$TARGET_DIR' is not a directory." >&2
    exit 1
fi
mkdir -p "$TARGET_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUISLE_EXEC=""

if [ -x "$SCRIPT_DIR/.venv/bin/cuisle" ]; then
    CUISLE_EXEC="$SCRIPT_DIR/.venv/bin/cuisle"
elif command -v cuisle >/dev/null 2>&1; then
    CUISLE_EXEC="$(command -v cuisle)"
else
    echo "Error: cannot find the cuisle executable." >&2
    echo "Run 'python3 -m venv .venv && .venv/bin/pip install -e .' first," >&2
    echo "or make sure cuisle is already on PATH." >&2
    exit 1
fi

CUISLE_EXEC="$(cd "$(dirname "$CUISLE_EXEC")" && pwd)/$(basename "$CUISLE_EXEC")"
LINK_PATH="$TARGET_DIR/cuisle"

if [ -L "$LINK_PATH" ]; then
    if [ "$(readlink "$LINK_PATH")" = "$CUISLE_EXEC" ]; then
        echo "Already installed: $LINK_PATH -> $CUISLE_EXEC"
    else
        echo "Error: '$LINK_PATH' is a symlink to a different target:" >&2
        echo "  $(readlink "$LINK_PATH")" >&2
        echo "Remove it manually if you want to replace it." >&2
        exit 1
    fi
elif [ -e "$LINK_PATH" ]; then
    echo "Error: '$LINK_PATH' exists and is not a symlink." >&2
    exit 1
else
    ln -s "$CUISLE_EXEC" "$LINK_PATH"
    echo "Installed: $LINK_PATH -> $CUISLE_EXEC"
fi

case ":$PATH:" in
    *":$TARGET_DIR:"*)
        ;;
    *)
        echo
        echo "Warning: '$TARGET_DIR' is not on your PATH." >&2
        echo "Add it in ~/.zshrc, for example:" >&2
        echo "  export PATH=\"$TARGET_DIR:\$PATH\"" >&2
        ;;
esac
