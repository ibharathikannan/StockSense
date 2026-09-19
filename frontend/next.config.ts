import type { NextConfig } from "next";

// Where the FastAPI backend lives. The browser only ever talks to this Next.js
// origin: /api/* is proxied server-side, so the httpOnly auth cookie is
// same-origin and no CORS is needed. NOTE: rewrites are resolved at build
// time, so set BACKEND_URL when running `next build` (see Dockerfile).
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
