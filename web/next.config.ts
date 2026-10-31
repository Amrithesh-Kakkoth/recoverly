import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // The browser only ever talks to this origin; the API (REST + SSE) is proxied, so no CORS.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/shop/:path*", destination: `${backend}/shop/:path*` },
    ];
  },
  compress: false, // gzip would buffer the SSE stream
};

export default config;
