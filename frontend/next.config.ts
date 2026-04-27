import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  trailingSlash: true,

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
