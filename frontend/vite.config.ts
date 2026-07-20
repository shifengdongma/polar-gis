import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = environment.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const geoserverProxyTarget = environment.VITE_GEOSERVER_PROXY_TARGET || 'http://localhost:8080'

  return {
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/geoserver': {
        target: geoserverProxyTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
  }
})
