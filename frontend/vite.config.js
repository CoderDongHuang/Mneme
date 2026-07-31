import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const configuredGateway = env.VITE_GATEWAY_TARGET || 'http://127.0.0.1:8080'
  const gateway = configuredGateway.replace('://localhost', '://127.0.0.1')
  return {
    plugins: [react()],
    test: { include: ['src/**/*.test.{js,jsx}'] },
    server: {
      port: 5173,
      proxy: {
        '/api': { target: gateway, changeOrigin: true },
        '/ws': { target: gateway.replace(/^http/, 'ws'), ws: true },
      },
    },
  }
})
