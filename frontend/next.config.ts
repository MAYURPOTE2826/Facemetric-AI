import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  // Report generation can take a while; don't let the dev proxy cut it off.
  experimental: { proxyTimeout: 240_000 },
};

export default nextConfig;
