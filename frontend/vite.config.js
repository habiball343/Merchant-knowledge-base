import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式下把 /api 代理到后端；后端地址可用根目录 .env 中的 APP_HOST / APP_PORT 调整
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', ['APP_'])
  const backend = `http://${env.APP_HOST || '127.0.0.1'}:${env.APP_PORT || '18100'}`
  return {
    plugins: [vue()],
    server: {
      host: '127.0.0.1',
      port: 15273,
      strictPort: true,
      proxy: { '/api': { target: backend, changeOrigin: true } },
    },
  }
})
