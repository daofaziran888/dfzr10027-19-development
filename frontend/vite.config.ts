import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端地址默认取本文件里写的端口，起服务时可以用 VITE_PROXY_TARGET 覆盖，
// 这样换端口调试或做启动探针时前端不用改代码。
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 关掉自动打开页面：起服务时只打印地址，不拉起浏览器
    open: false,
    strictPort: false,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        bypass(req) {
          // 浏览器页面导航的 Accept 含 text/html，交给 SPA 历史路由处理；
          // 否则 /api_service 这类以 /api 开头的前端路由会被误转发到后端而返回 404。
          // 但 /export 下载用 window.open 触发、同样带 text/html，必须继续走代理取文件流。
          // 接口 fetch 不带 text/html，仍正常代理到后端。
          const isHtmlNavigation = req.headers.accept?.includes('text/html')
          const isExportDownload = req.url?.includes('/export')
          if (isHtmlNavigation && !isExportDownload) {
            return req.url ?? '/'
          }
          return undefined
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
