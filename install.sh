#!/bin/sh
# ASM — Agent Skill Manager installer
# Usage: curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
set -eu

ASM_WHEEL_URL="${ASM_WHEEL_URL:-https://github.com/gil-kapel/asm/releases/latest/download/asm-py3-none-any.whl}"
MIN_PYTHON="3.10"

# ── Helpers ──────────────────────────────────────────────────────────

info()  { printf '  \033[1;34m>\033[0m %s\n' "$*"; }
ok()    { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
warn()  { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }
err()   { printf '  \033[1;31m✘\033[0m %s\n' "$*" >&2; exit 1; }

has() { command -v "$1" >/dev/null 2>&1; }

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

# ── Install via uv tool ─────────────────────────────────────────────

info "Uninstalling existing asm tool (if present)..."
uv tool uninstall asm >/dev/null 2>&1 || true
ok "Previous asm tool removed (or not installed)"

info "Installing asm CLI from release wheel..."
if ! uv tool install --python "$PYTHON" --reinstall "$ASM_WHEEL_URL"; then
    err "Failed to install from $ASM_WHEEL_URL. If this project has no releases yet, install from source:
    uv tool install git+https://github.com/gil-kapel/asm"
fi
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
    err "Installation failed. Try manually: uv tool install --reinstall $ASM_WHEEL_URL"
fi

# ── Uninstall hint ───────────────────────────────────────────────────

printf '  To uninstall: \033[2muv tool uninstall asm\033[0m\n\n'
