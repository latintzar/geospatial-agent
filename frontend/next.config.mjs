/** @type {import('next').NextConfig} */
const nextConfig = { output: 'standalone', assetPrefix: process.env.NODE_ENV === 'production' ? '/apps/geospatial-agent' : undefined };
export default nextConfig;
