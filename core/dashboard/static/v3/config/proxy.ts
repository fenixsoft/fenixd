/**
 * 开发期代理：/api 转发到本机 fenixd daemon（默认 8787）。
 * build 产物与 daemon 同源部署，不经过此代理。
 */
export default {
  dev: {
    '/api/': {
      target: 'http://127.0.0.1:8787',
      changeOrigin: true,
    },
  },
};
