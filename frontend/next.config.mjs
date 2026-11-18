/** @type {import('next').NextConfig} */
const api = process.env.JEDOC_API_PROXY || "http://127.0.0.1:8000";

const nextConfig = {
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
