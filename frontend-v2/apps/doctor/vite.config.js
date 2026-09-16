import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const appRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, appRoot, 'VITE_')
  const backendBaseUrl = env.VITE_BACKEND_BASE_URL?.trim() || '/ai-api'
  const smartClientId = env.VITE_SMART_CLIENT_ID?.trim() || ''
  const smartScopes = env.VITE_SMART_SCOPES?.trim() || ''
  const smartIssuerAllowlist =
    env.VITE_SMART_ISSUER_ALLOWLIST?.trim() || ''

  return {
    base: '/ai-consult/',
    plugins: [vue()],
    define: {
      'import.meta.env.VITE_BACKEND_BASE_URL': JSON.stringify(backendBaseUrl),
      'import.meta.env.VITE_SMART_CLIENT_ID': JSON.stringify(smartClientId),
      'import.meta.env.VITE_SMART_SCOPES': JSON.stringify(smartScopes),
      'import.meta.env.VITE_SMART_ISSUER_ALLOWLIST': JSON.stringify(
        smartIssuerAllowlist,
      ),
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
      rollupOptions: {
        input: {
          index: fileURLToPath(new URL('index.html', import.meta.url)),
          launch: fileURLToPath(new URL('launch.html', import.meta.url)),
        },
      },
    },
  }
})
