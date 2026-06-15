import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // 放行 cloudflared 穿透域名（*.trycloudflare.com）；localhost 始终允许。
    // 发他人测试用，让外部 Host 头通过 Vite 校验；不需要时可移除。
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      // 开发期把 /api 请求代理到 FastAPI 后端，避免 CORS
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
