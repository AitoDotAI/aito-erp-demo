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

    # Load .env if present
    if [ -f .env ]; then
      set -a; source .env; set +a
      echo "  .env loaded"
    elif [ -f .env.example ]; then
      cp .env.example .env
      set -a; source .env; set +a
      echo "  .env created from .env.example"
    fi

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
