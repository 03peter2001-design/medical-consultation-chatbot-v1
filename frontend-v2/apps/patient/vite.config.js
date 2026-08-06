import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const appRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, appRoot, 'VITE_')
  const backendBaseUrl = env.VITE_BACKEND_BASE_URL?.trim() || '/api'

  return {
    base: '/',
    plugins: [vue()],
    define: {
      'import.meta.env.VITE_BACKEND_BASE_URL': JSON.stringify(backendBaseUrl),
    },
    resolve: {
      alias: {
        '@medical/shared': fileURLToPath(
          new URL('../../packages/shared/src', import.meta.url),
        ),
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
  }
})
