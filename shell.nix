{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  name = "aito-erp-demo";

  buildInputs = with pkgs; [
    # Node.js
    nodejs_20
    nodePackages.npm

    # Dev tools
    git
    curl
    jq

    # For PDF/screenshot generation of the product sheet
    python3
    python3Packages.weasyprint

    # Static file serving during development
    nodePackages.serve

    # Code quality
    nodePackages.prettier
  ];

  shellHook = ''
    echo ""
    echo "  Predictive ERP Demo"
    echo "  ─────────────────────────────────────"
    echo "  Node.js  $(node --version)"
    echo "  npm      $(npm --version)"
    echo ""

    # Load .env if present
    if [ -f .env ]; then
      set -a; source .env; set +a
      echo "  .env loaded"
    elif [ -f .env.example ]; then
      cp .env.example .env
      set -a; source .env; set +a
      echo "  .env created from .env.example"
    fi

    # Check node_modules
    if [ ! -d "node_modules" ]; then
      echo "  ⚠  No node_modules — run: npm install"
    else
      echo "  ✓  node_modules ready"
    fi

    echo ""
    echo "  Commands:"
    echo "    npm run dev          Start Vite dev server (hot reload)"
    echo "    npm run build        Production build → dist/"
    echo "    npm run preview      Preview production build locally"
    echo "    serve dist           Serve built files statically"
    echo "    serve . -p 3000      Serve HTML mock directly (no build)"
    echo ""
    echo "  Quick demo (no build needed):"
    echo "    serve . -p 3000"
    echo "    open http://localhost:3000/predictive-erp.html"
    echo ""
    echo "  Reference files:"
    echo "    predictive-erp.html        Interactive HTML mock (source of truth)"
    echo "    predictive-erp-CLAUDE.md   Full spec for CC build"
    echo "  ─────────────────────────────────────"
  '';

  NODE_ENV = "development";
  NODE_OPTIONS = "--max-old-space-size=4096";
}
