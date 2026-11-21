/**
 * 开发期代理：/api、/screenshots、/proto 转发到本机 fenixd daemon（默认 8787）。
 * build 产物与 daemon 同源部署，不经过此代理。
 */
export default {
  dev: {
    '/api/': {
      target: 'http://127.0.0.1:8787',
      changeOrigin: true,
    },
    '/screenshots/': {
      target: 'http://127.0.0.1:8787',
      changeOrigin: true,
    },
    // /proto/<project>/<spec>/... 原型静态伺服（add-proto-dashboard-serving）：
    // 开发期不转发则原型页/批注回流链接落在 devServer 404（code-review item 2b1340d69d47）
    '/proto/': {
      target: 'http://127.0.0.1:8787',
      changeOrigin: true,
    },
  },
};
