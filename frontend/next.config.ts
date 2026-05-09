import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  trailingSlash: true,
  // Page-route trailing slashes are right for our static export, but the
  // redirect that enforces them creates a 308 ↔ 307 ping-pong with the
  // FastAPI proxy below: Next adds the slash, FastAPI strips it. Skip
  // the redirect so /api/* requests pass through whichever form the
  // client sent.
  skipTrailingSlashRedirect: true,

  // Proxy API calls to the FastAPI backend — same origin, no CORS
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8401/api/:path*",
      },
    ];
  },
};

export default nextConfig;
