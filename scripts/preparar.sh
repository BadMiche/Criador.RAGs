#!/usr/bin/env bash
# Prepara o Python do Criador.RAGs (uma vez) e imprime o caminho do interpretador.
# Usa um venv próprio porque o Python do Homebrew (Mac) recusa `pip install` global.
set -euo pipefail
VENV="${CRIADOR_RAGS_VENV:-$HOME/.criador-rags/venv}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" >&2
fi
if ! "$VENV/bin/python" -c "import pymupdf4llm, markitdown, yaml, requests, PIL" 2>/dev/null; then
  "$VENV/bin/python" -m pip install -q --upgrade pip >&2
  "$VENV/bin/python" -m pip install -q -r "$RAIZ/requirements.txt" >&2
fi
echo "$VENV/bin/python"
