import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

// FACEGATE_API_URL (e.g. in frontend/.env.local) points the dev proxy at a non-default API port.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: loadEnv(mode, process.cwd(), 'FACEGATE_').FACEGATE_API_URL || 'http://127.0.0.1:8000', changeOrigin: true, ws: true },
    },
  },
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-')) return 'charts'
          if (id.includes('node_modules/motion')) return 'motion'
          if (id.includes('node_modules/react') || id.includes('node_modules/@tanstack')) return 'vendor'
        },
      },
    },
  },
}))
