import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // Static export for production — FastAPI's StaticFiles(html=True) mount in
  // src/app.py serves the built files from frontend/out, and /api/* routes are
  // handled by FastAPI from the same port. One process, one port.
  // Dev still runs `next dev` + uvicorn separately on different ports, so dev
  // keeps the rewrite below.
  ...(isDev ? {} : { output: "export" }),

  trailingSlash: true,
  // Page-route trailing slashes match what StaticFiles(html=True) resolves
  // (`/orders/` → `orders/index.html`). Skip the redirect so dev `/api/*`
  // requests pass through whichever form the client sent and avoid a
  // 308 ↔ 307 ping-pong with FastAPI.
  skipTrailingSlashRedirect: true,

  // Dev only: proxy API calls to the FastAPI backend on its dev port.
  // In production no rewrite is needed (FastAPI serves /api/* from the same
  // origin as the static export).
  ...(isDev
    ? {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: "http://localhost:8401/api/:path*",
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
