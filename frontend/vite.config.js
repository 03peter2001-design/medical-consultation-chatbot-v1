import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/ai-consult/',
  plugins: [vue()],
  server: {
    port: 5173,
  },
  preview: {
    port: 4173,
  },
})
