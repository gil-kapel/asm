#!/bin/sh
# ASM — Agent Skill Manager installer
# Usage: curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/install.sh | sh
set -eu

ASM_REPO="https://github.com/gil-kapel/asm.git"
ASM_HOME="${ASM_HOME:-$HOME/.asm-cli}"
MIN_PYTHON="3.10"
ASM_SOURCE_MODE="${ASM_SOURCE_MODE:-auto}" # auto | local | remote

# ── Helpers ──────────────────────────────────────────────────────────

info()  { printf '  \033[1;34m>\033[0m %s\n' "$*"; }
ok()    { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
warn()  { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }
err()   { printf '  \033[1;31m✘\033[0m %s\n' "$*" >&2; exit 1; }

has() { command -v "$1" >/dev/null 2>&1; }

resolve_script_dir() {
    # Works for "sh ./install.sh" and absolute/relative execution.
    # When piped ("curl ... | sh"), $0 is "sh" and this resolves to empty.
    case "$0" in
        /*) script_path="$0" ;;
        *) script_path="$PWD/$0" ;;
    esac
    if [ -f "$script_path" ]; then
        (cd "$(dirname "$script_path")" && pwd)
    else
        printf '%s' ""
    fi
}

version_gte() {
    # Returns 0 if $1 >= $2 (dot-separated version comparison)
    printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1 | grep -qx "$2"
}

# ── Banner ───────────────────────────────────────────────────────────

printf '\n  \033[1mASM — Agent Skill Manager\033[0m\n'
printf '  %s\n\n' "────────────────────────────"

# ── Check Python ─────────────────────────────────────────────────────

PYTHON=""
for candidate in python3 python; do
    if has "$candidate"; then
        py_version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" 2>/dev/null || continue
        if version_gte "$py_version" "$MIN_PYTHON"; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python >= $MIN_PYTHON is required but not found. Install it first: https://www.python.org/downloads/"
fi
ok "Python $py_version ($PYTHON)"

# ── Check / install uv ──────────────────────────────────────────────

if has uv; then
    ok "uv $(uv --version 2>/dev/null | head -1)"
else
    info "Installing uv..."
    if has curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif has wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        err "Neither curl nor wget found. Install one of them first."
    fi

    # Source uv's env so it's available in this session
    UV_ENV="$HOME/.local/bin"
    CARGO_ENV="$HOME/.cargo/env"
    if [ -f "$CARGO_ENV" ]; then
        . "$CARGO_ENV"
    fi
    if [ -d "$UV_ENV" ]; then
        export PATH="$UV_ENV:$PATH"
    fi

    has uv || err "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    ok "uv installed"
fi

# ── Check git ────────────────────────────────────────────────────────

has git || err "git is required but not found."

# ── Resolve source mode ──────────────────────────────────────────────

SCRIPT_DIR="$(resolve_script_dir)"
LOCAL_SOURCE=""
if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/.git" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    LOCAL_SOURCE="$SCRIPT_DIR"
fi

INSTALL_SOURCE=""
case "$ASM_SOURCE_MODE" in
    local)
        [ -n "$LOCAL_SOURCE" ] || err "ASM_SOURCE_MODE=local but no local ASM repo was detected."
        INSTALL_SOURCE="$LOCAL_SOURCE"
        info "Using local source: $INSTALL_SOURCE"
        ;;
    remote)
        INSTALL_SOURCE="$ASM_HOME"
        ;;
    auto)
        if [ -n "$LOCAL_SOURCE" ]; then
            INSTALL_SOURCE="$LOCAL_SOURCE"
            info "Detected local ASM repo — installing from local source"
        else
            INSTALL_SOURCE="$ASM_HOME"
        fi
        ;;
    *)
        err "Invalid ASM_SOURCE_MODE='$ASM_SOURCE_MODE' (expected: auto|local|remote)."
        ;;
esac

# ── Clone or update repo ────────────────────────────────────────────

if [ "$INSTALL_SOURCE" = "$ASM_HOME" ]; then
    if [ -d "$ASM_HOME/.git" ]; then
        info "Updating existing installation..."
        git -C "$ASM_HOME" pull --ff-only --quiet 2>/dev/null || warn "git pull failed — continuing with existing version"
        ok "Updated $ASM_HOME"
    else
        if [ -d "$ASM_HOME" ]; then
            warn "$ASM_HOME exists but is not a git repo — removing"
            rm -rf "$ASM_HOME"
        fi
        info "Cloning asm..."
        git clone --depth 1 --quiet "$ASM_REPO" "$ASM_HOME"
        ok "Cloned to $ASM_HOME"
    fi
fi

# ── Install via uv tool ─────────────────────────────────────────────

if uv tool list 2>/dev/null | grep -q '^asm '; then
    info "Existing asm tool found — uninstalling first..."
    uv tool uninstall asm >/dev/null 2>&1 || warn "Failed to uninstall previous asm tool cleanly"
    ok "Removed previous asm tool"
fi

info "Installing asm CLI..."
uv tool install --editable "$INSTALL_SOURCE" --python "$PYTHON" >/dev/null 2>&1
ok "Installed asm CLI"

# ── Verify ───────────────────────────────────────────────────────────

UV_TOOL_BIN="$HOME/.local/bin"

if has asm; then
    ok "asm $(asm --version 2>/dev/null)"
    printf '\n  \033[1;32mReady!\033[0m Run \033[1masm init\033[0m in any project to get started.\n\n'
elif [ -x "$UV_TOOL_BIN/asm" ]; then
    warn "asm is installed but not on PATH."
    printf '\n  Add this to your shell profile:\n'
    printf '    export PATH="%s:$PATH"\n\n' "$UV_TOOL_BIN"
    printf '  Then restart your shell and run: \033[1masm init\033[0m\n\n'
else
    err "Installation failed. Try manually: uv tool install -e $INSTALL_SOURCE"
fi

# ── Uninstall hint ───────────────────────────────────────────────────

printf '  To uninstall: \033[2muv tool uninstall asm && rm -rf %s\033[0m\n\n' "$ASM_HOME"
