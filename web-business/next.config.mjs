/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  env: {
    CAIRN_API_URL: process.env.CAIRN_API_URL || 'http://localhost:8765',
    CAIRN_API_KEY: process.env.CAIRN_API_KEY || 'claw-dev-key-change-in-production',
    PHLOE_API_URL: process.env.PHLOE_API_URL || 'https://phloe.co.uk',
    PHLOE_TENANT_SLUG: process.env.PHLOE_TENANT_SLUG || 'nbne',
  },
};

export default nextConfig;
