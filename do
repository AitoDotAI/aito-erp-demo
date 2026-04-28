#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source .env if present
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

# Ports: frontend on 8400 (user-facing), backend on 8401 (internal)
PORT_FRONTEND=8400
PORT_BACKEND=8401

cmd_help() {
  cat <<EOF
Usage: ./do <command>

Commands:
  help            Show this help
  dev             Start both backend + frontend (http://localhost:${PORT_FRONTEND})
  backend-dev     Start backend only (port ${PORT_BACKEND})
  frontend-dev    Start frontend only (port ${PORT_FRONTEND}, proxies API to ${PORT_BACKEND})
  frontend-build  Build Next.js static export to frontend/out/
  stop            Stop all running dev servers
  restart         Stop then start dev servers
  demo            Open the demo in browser
  load-data       Upload sample data to Aito
                  Use --tenant=<metsa|aurora|studio|all> for multi-tenant
  reset-data      Drop and reload all Aito tables (accepts --tenant=...)
  generate-personas
                  (Re)generate per-tenant fixtures into data/<tenant>/
  clear-cache     Clear in-memory and Aito persistent cache
  test            Run the unit test suite
  booktest        Run project-portfolio quality tests (offline + live)
  fmt             Format code
  check           Run all pre-merge checks (test + fmt)
  npm-install     Install frontend npm dependencies
  uv-sync         Sync Python dependencies
  setup           Full setup (uv sync + npm install)
  typecheck       Run TypeScript type checking
  lint            Lint frontend code
  screenshot      Capture screenshot(s): ./do screenshot [view|all]
                  Views: po-queue smart-entry approval anomalies supplier
                         rules catalog pricing demand inventory overview
  product-sheet   Compile docs/product-sheet/product-sheet.typ → PDF

EOF
}

cmd_dev() {
  echo "Starting Predictive ERP"
  echo "  Backend:  http://localhost:${PORT_BACKEND} (internal)"
  echo "  Frontend: http://localhost:${PORT_FRONTEND} (open this)"
  echo ""

  # Start backend in background
  cd "$SCRIPT_DIR"
  uv run uvicorn src.app:app --reload --port "$PORT_BACKEND" &
  BACKEND_PID=$!

  # Start frontend in foreground
  cd "$SCRIPT_DIR/frontend"
  npx next dev -p "$PORT_FRONTEND" &
  FRONTEND_PID=$!

  # Trap to kill both on exit
  trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM EXIT

  echo ""
  echo "  Both servers running. Press Ctrl+C to stop."
  wait
}

cmd_backend_dev() {
  echo "Starting Predictive ERP API on http://localhost:${PORT_BACKEND}"
  cd "$SCRIPT_DIR"
  uv run uvicorn src.app:app --reload --port "$PORT_BACKEND"
}

cmd_frontend_dev() {
  echo "Starting Next.js dev server on http://localhost:${PORT_FRONTEND}"
  echo "  API proxy → http://localhost:${PORT_BACKEND}"
  cd "$SCRIPT_DIR/frontend"
  npx next dev -p "$PORT_FRONTEND"
}

cmd_frontend_build() {
  echo "Building Next.js static export..."
  cd "$SCRIPT_DIR/frontend"
  npx next build
  echo "Built to frontend/out/ — ./do backend-dev will serve it."
}

cmd_demo() {
  local url="http://localhost:${PORT_FRONTEND}"
  if curl -s -o /dev/null "$url" 2>/dev/null; then
    echo "Opening $url"
    if command -v xdg-open &>/dev/null; then
      xdg-open "$url"
    elif command -v open &>/dev/null; then
      open "$url"
    else
      echo "Open manually: $url"
    fi
  else
    echo "Not running. Start with: ./do dev"
  fi
}

_kill_port() {
  local port="$1"
  # Try fuser first
  if command -v fuser &>/dev/null; then
    fuser -k "${port}/tcp" 2>/dev/null || true
    return
  fi
  # Fallback to ss + kill
  if command -v ss &>/dev/null; then
    local pids
    pids=$(ss -tlnp 2>/dev/null | grep -oP "(?<=pid=)\d+" | sort -u)
    for pid in $pids; do
      local pport
      pport=$(ss -tlnp 2>/dev/null | grep "pid=$pid" | grep -oE ":[0-9]+" | head -1 | tr -d ':')
      if [[ "$pport" == "$port" ]]; then
        kill "$pid" 2>/dev/null || true
      fi
    done
  fi
  # Fallback to lsof
  if command -v lsof &>/dev/null; then
    lsof -ti:"$port" 2>/dev/null | xargs -r kill 2>/dev/null || true
  fi
}

cmd_stop() {
  echo "Stopping dev servers..."
  pkill -f "uvicorn src.app" 2>/dev/null || true
  pkill -f "next dev.*-p ${PORT_FRONTEND}" 2>/dev/null || true
  pkill -f "next-server" 2>/dev/null || true
  _kill_port "${PORT_BACKEND}"
  _kill_port "${PORT_FRONTEND}"
  sleep 2
  echo "Stopped."
}

cmd_restart() {
  cmd_stop
  cmd_dev
}

cmd_load_data() {
  cd "$SCRIPT_DIR"
  # Forward extra args (e.g. --tenant=metsa, --tenant=all)
  uv run python -m src.data_loader "$@"
}

cmd_generate_personas() {
  # Regenerate per-tenant fixtures into data/<tenant>/. Run once
  # before --tenant=all if you change anything in generate_personas.py.
  cd "$SCRIPT_DIR"
  uv run python data/generate_personas.py
}

cmd_reset_data() {
  cd "$SCRIPT_DIR"
  uv run python -m src.data_loader --reset "$@"
}

cmd_clear_cache() {
  echo "Clearing caches..."
  cd "$SCRIPT_DIR"
  uv run python -c "
from src.config import load_config
from src.aito_client import AitoClient
from src.cache import init_persistent_cache, clear_all
client = AitoClient(load_config())
init_persistent_cache(client)
clear_all()
print('Done. Restart ./do dev to recompute predictions.')
"
}

cmd_test() {
  cd "$SCRIPT_DIR"
  uv run pytest tests/ -v
}

cmd_booktest() {
  # Project portfolio quality tests. Offline tests check the fixture
  # data carries the engineered signal; live tests (requires
  # AITO_API_URL + AITO_API_KEY + loaded `projects` table) check Aito
  # picks that signal up via _predict / _relate.
  cd "$SCRIPT_DIR"
  uv run pytest tests/test_project_booktest.py -v "$@"
}

cmd_fmt() {
  echo "No formatter configured yet."
}

cmd_check() {
  cmd_test
  cmd_fmt
}

cmd_npm_install() {
  echo "Installing frontend dependencies..."
  cd "$SCRIPT_DIR/frontend"
  npm install
}

cmd_uv_sync() {
  echo "Syncing Python dependencies..."
  cd "$SCRIPT_DIR"
  uv sync
}

cmd_setup() {
  cmd_uv_sync
  cmd_npm_install
  echo "Setup complete."
}

cmd_typecheck() {
  echo "Running TypeScript type check..."
  cd "$SCRIPT_DIR/frontend"
  npx tsc --noEmit
}

_find_chrome() {
  # 1. Playwright-managed browsers
  for c in ${PLAYWRIGHT_BROWSERS_PATH:-/nonexistent}/chromium-*/chrome-linux/chrome; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  # 2. Nix playwright-chromium package
  for c in /nix/store/*playwright-chromium*/chrome-linux/chrome; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  # 3. Nix google-chrome
  for c in /nix/store/*google-chrome-*/share/google/chrome/chrome; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  # 4. PATH lookups
  for cmd in chromium chromium-browser google-chrome; do
    local path
    path=$(command -v "$cmd" 2>/dev/null)
    [[ -n "$path" && -x "$path" ]] && { echo "$path"; return; }
  done
  echo ""
}

cmd_screenshot() {
  # ./do screenshot [view-or-all] [tenant]
  # tenant ∈ metsa | aurora | studio | all  (default: metsa)
  # When tenant=all, every view is captured three times with the
  # tenant id suffixed onto the filename.
  local view="${2:-all}"
  local tenant="${3:-metsa}"
  local chrome
  chrome=$(_find_chrome)
  if [[ -z "$chrome" ]]; then
    echo "Error: chromium not found. Install chromium or set PLAYWRIGHT_BROWSERS_PATH." >&2
    exit 1
  fi

  # Ensure playwright-core is available
  if [[ ! -d "$SCRIPT_DIR/frontend/node_modules/playwright-core" ]]; then
    (cd "$SCRIPT_DIR/frontend" && npm install --save-dev playwright-core@1.52.0 --silent)
  fi

  mkdir -p "$SCRIPT_DIR/screenshots"

  local base_url="http://localhost:${PORT_FRONTEND}"
  # Verify server is running
  if ! curl -s -o /dev/null "$base_url" 2>/dev/null; then
    echo "Error: frontend not running at $base_url. Start with: ./do dev" >&2
    exit 1
  fi

  cd "$SCRIPT_DIR/frontend"
  node -e "
    const { chromium } = require('playwright-core');

    // Per-tenant route maps so we don't bother capturing views that
    // are hidden in that profile. Mirrors hideRoutes in
    // frontend/lib/tenants.ts.
    const ROUTES_BY_TENANT = {
      metsa: [
        ['00-landing',     '/'],
        ['01-po-queue',    '/po-queue/'],
        ['02-smart-entry', '/smart-entry/'],
        ['03-approval',    '/approval/'],
        ['04-anomalies',   '/anomalies/'],
        ['05-supplier',    '/supplier/'],
        ['06-rules',       '/rules/'],
        ['10-inventory',   '/inventory/'],
        ['11-projects',    '/projects/'],
        ['14-overview',    '/overview/'],
      ],
      aurora: [
        ['00-landing',         '/'],
        ['01-po-queue',        '/po-queue/'],
        ['02-smart-entry',     '/smart-entry/'],
        ['04-anomalies',       '/anomalies/'],
        ['05-supplier',        '/supplier/'],
        ['06-rules',           '/rules/'],
        ['07-catalog',         '/catalog/'],
        ['08-pricing',         '/pricing/'],
        ['09-demand',          '/demand/'],
        ['10-inventory',       '/inventory/'],
        ['13-recommendations', '/recommendations/'],
        ['14-overview',        '/overview/'],
      ],
      studio: [
        ['00-landing',     '/'],
        ['01-po-queue',    '/po-queue/'],
        ['02-smart-entry', '/smart-entry/'],
        ['03-approval',    '/approval/'],
        ['04-anomalies',   '/anomalies/'],
        ['05-supplier',    '/supplier/'],
        ['06-rules',       '/rules/'],
        ['11-projects',    '/projects/'],
        ['12-utilization', '/utilization/'],
        ['14-overview',    '/overview/'],
      ],
    };

    const tenantArg = '$tenant';
    const tenants = (tenantArg === 'all')
      ? ['metsa', 'aurora', 'studio']
      : [tenantArg];

    (async () => {
      const browser = await chromium.launch({
        executablePath: '$chrome',
        headless: true,
        args: ['--no-sandbox', '--disable-gpu']
      });

      const viewArg = '$view';
      let totalCaptured = 0, totalFailed = 0;

      for (const tenant of tenants) {
        // Fresh context per tenant so localStorage seed sticks for
        // every navigation in that tenant, then clears for the next.
        const ctx = await browser.newContext({
          viewport: { width: 1440, height: 900 },
        });
        await ctx.addInitScript((t) => {
          window.localStorage.setItem('demoTenant', t);
        }, tenant);
        const page = await ctx.newPage();

        let routes = ROUTES_BY_TENANT[tenant] || ROUTES_BY_TENANT.metsa;
        if (viewArg !== 'all') {
          routes = routes.filter(r => r[1].includes(viewArg));
          if (routes.length === 0) {
            console.error('Unknown view: ' + viewArg);
            process.exit(1);
          }
        }

        // Suffix tenant id when we're capturing more than one tenant,
        // otherwise keep the legacy filename (so single-tenant runs
        // still produce 01-po-queue.png).
        const suffix = (tenants.length > 1) ? '-' + tenant : '';
        console.log('--- Tenant: ' + tenant + ' ---');
        for (const [name, path] of routes) {
          const file = name + suffix + '.png';
          try {
            await page.goto('$base_url' + path, { waitUntil: 'networkidle', timeout: 60000 });
            await page.waitForTimeout(2500);
            await page.screenshot({ path: '$SCRIPT_DIR/screenshots/' + file, fullPage: false });
            console.log('  captured ' + file);
            totalCaptured++;
          } catch (e) {
            console.log('  FAILED ' + file + ': ' + e.message.substring(0, 100));
            totalFailed++;
          }
        }

        await ctx.close();
      }

      await browser.close();
      console.log('Done. ' + totalCaptured + ' captured, ' + totalFailed + ' failed.');
    })();
  "
}

cmd_lint() {
  echo "Linting frontend..."
  cd "$SCRIPT_DIR/frontend"
  npx next lint 2>/dev/null || echo "No linter configured."
}

cmd_product_sheet() {
  echo "Compiling product sheet..."
  cd "$SCRIPT_DIR"
  if ! command -v typst >/dev/null 2>&1; then
    echo "  typst not on PATH — try: nix-shell"
    exit 1
  fi
  typst compile docs/product-sheet/product-sheet.typ docs/product-sheet/product-sheet.pdf
  echo "  ✓ docs/product-sheet/product-sheet.pdf"
}

case "${1:-help}" in
  help)            cmd_help ;;
  dev)             cmd_dev ;;
  backend-dev)     cmd_backend_dev ;;
  frontend-dev)    cmd_frontend_dev ;;
  frontend-build)  cmd_frontend_build ;;
  stop)            cmd_stop ;;
  restart)         cmd_restart ;;
  demo)            cmd_demo ;;
  load-data)       shift; cmd_load_data "$@" ;;
  reset-data)      shift; cmd_reset_data "$@" ;;
  generate-personas) cmd_generate_personas ;;
  clear-cache)     cmd_clear_cache ;;
  test)            cmd_test ;;
  booktest)        shift; cmd_booktest "$@" ;;
  fmt)             cmd_fmt ;;
  check)           cmd_check ;;
  npm-install)     cmd_npm_install ;;
  uv-sync)        cmd_uv_sync ;;
  setup)           cmd_setup ;;
  typecheck)       cmd_typecheck ;;
  lint)            cmd_lint ;;
  screenshot)      cmd_screenshot "$@" ;;
  product-sheet)   cmd_product_sheet ;;
  *)
    echo "Unknown command: $1" >&2
    cmd_help
    exit 1
    ;;
esac
