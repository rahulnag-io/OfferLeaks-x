import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Server-side code (server components, route handlers) reads
  // API_URL directly; only NEXT_PUBLIC_* vars reach the browser bundle.
};

export default nextConfig;
