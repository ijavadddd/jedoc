/** @type {import('next').NextConfig} */
const api = process.env.JEDOC_API_PROXY || "http://127.0.0.1:8000";

const nextConfig = {
  // Docker / README use 127.0.0.1; Next blocks cross-origin /_next assets without this.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Cursor turns can sit quiet for longer than Next's 30s dev proxy limit.
  experimental: {
    proxyTimeout: 900_000,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/ws/:path*", destination: `${api}/ws/:path*` },
    ];
  },
};

export default nextConfig;
