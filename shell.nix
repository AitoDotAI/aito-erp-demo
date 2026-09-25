{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  name = "aito-erp-demo";

  buildInputs = with pkgs; [
    # Frontend (npm ships with nodejs — no separate package).
    # 22 is the current LTS; 20 went EOL and nixpkgs now marks it insecure.
    nodejs_22

    # Backend: ./do drives every Python command through uv
    python3
    uv

    # Dev tools
    git
    curl
    jq

    # For PDF/screenshot generation of the product sheet
    python3Packages.weasyprint
    typst

    # Static file serving during development
    serve

    # Code quality
    prettier
  ];

  shellHook = ''
    echo ""
    echo "  Predictive ERP Demo"
    echo "  ─────────────────────────────────────"
    echo "  Node.js  $(node --version)"
    echo "  npm      $(npm --version)"
    echo "  Python   $(python3 --version | cut -d' ' -f2)"
    echo "  uv       $(uv --version | cut -d' ' -f2)"
    echo ""

    # The `aitoai` SDK pulls pandas, whose numpy wheel links against
    # libstdc++ — which a nix shell does not put on the loader path.
    # Without this, importing src.aito_client dies at `import numpy`.
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$LD_LIBRARY_PATH"

    # Load .env if present. A variable already exported when the shell
    # starts wins over the file (same rule as ./do and src/config.py):
    # a plain `set -a; source .env` let the file win, which is how on
    # 2026-09-20 a run pointed at a local engine wrote to production.
    _load_env_file() {
      local name kv
      local -a explicit=()
      while IFS= read -r name; do
        [ -n "''${!name:-}" ] && explicit+=("$name=''${!name}")
      done < <(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p' "$1")
      set -a; source "$1"; set +a
      for kv in ''${explicit[@]+"''${explicit[@]}"}; do export "$kv"; done
    }
    if [ -f .env ]; then
      _load_env_file .env
      echo "  .env loaded"
    elif [ -f .env.example ]; then
      cp .env.example .env
      _load_env_file .env
      echo "  .env created from .env.example"
    fi
    unset -f _load_env_file

    # Dependencies live in frontend/ (npm) and .venv/ (uv)
    if [ ! -d "frontend/node_modules" ] || [ ! -d ".venv" ]; then
      echo "  ⚠  Dependencies missing — run: ./do setup"
    else
      echo "  ✓  Dependencies ready"
    fi

    echo ""
    echo "  Commands (see ./do help for the full list):"
    echo "    ./do dev             Next.js on :8400 + FastAPI on :8401"
    echo "    ./do load-data       Upload fixtures to Aito"
    echo "    ./do check           Pre-merge gate (test + fmt)"
    echo "  ─────────────────────────────────────"
  '';

  NODE_ENV = "development";
  NODE_OPTIONS = "--max-old-space-size=4096";
}
