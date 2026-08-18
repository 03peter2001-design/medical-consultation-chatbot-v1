import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'


export default defineConfig({
  base: '/ai-consult/',
  publicDir: '../pic',
  plugins: [vue(), vueDevTools()],
  server: {
    port: 5173,
  },
  preview: {
    port: 4173,
  },
})
