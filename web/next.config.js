/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output: produces a .next/standalone folder with a trimmed
  // node_modules + server.js entrypoint, so the production Docker image
  // can run without bundling the full node_modules tree. The deploy
  // Dockerfile copies .next/standalone + .next/static + public into a
  // minimal node:20-alpine runner image.
  output: 'standalone',
  env: {
    CLAW_API_URL: process.env.CLAW_API_URL || process.env.DEEK_API_URL || 'http://localhost:8765',
    DEEK_API_KEY: process.env.DEEK_API_KEY || process.env.DEEK_API_KEY || 'deek-dev-key-change-in-production',
  },
}

module.exports = nextConfig
