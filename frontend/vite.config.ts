import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 3000,
      strictPort: false,
      proxy: {
        '/api': {
          target: env.VITE_DEV_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      target: 'baseline-widely-available',
      sourcemap: mode !== 'production',
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const moduleId = id.replaceAll('\\', '/')
            if (
              moduleId.includes('/node_modules/react/') ||
              moduleId.includes('/node_modules/react-dom/') ||
              moduleId.includes('/node_modules/react-router-dom/')
            )
              return 'react'
            if (moduleId.includes('/node_modules/axios/') || moduleId.includes('/node_modules/@tanstack/react-query/'))
              return 'data'
            if (moduleId.includes('/node_modules/motion/')) return 'motion'
            if (
              moduleId.includes('/node_modules/katex/') ||
              moduleId.includes('/node_modules/rehype-katex/') ||
              moduleId.includes('/node_modules/remark-math/') ||
              moduleId.includes('/node_modules/micromark-extension-math/')
            )
              return 'math'
            if (
              moduleId.includes('/node_modules/recharts/') ||
              moduleId.includes('/node_modules/victory-vendor/') ||
              moduleId.includes('/node_modules/d3-')
            )
              return 'charts'
          },
        },
      },
    },
    optimizeDeps: {
      include: ['react', 'react-dom', 'react-router-dom', 'lucide-react'],
    },
  }
})
