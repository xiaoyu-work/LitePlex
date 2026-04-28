/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_URL || 'http://localhost:8088'

const nextConfig = {
  reactStrictMode: false, // Disable StrictMode to prevent double rendering in development
  async rewrites() {
    return [
      {
        source: '/api/stop',
        destination: `${backendUrl}/api/stop`,
      },
      {
        source: '/api/config',
        destination: `${backendUrl}/api/config`,
      },
      {
        source: '/api/health',
        destination: `${backendUrl}/api/health`,
      },
    ]
  },
}

module.exports = nextConfig
