// https://umijs.org/config/
import { defineConfig } from '@umijs/max';
import defaultSettings from './defaultSettings';
import proxy from './proxy';
import routes from './routes';

export default defineConfig({
  // 产物文件名带内容 hash，浏览器长缓存友好
  hash: true,

  // daemon 以 dist/ 子路径服务本应用，资源必须走相对路径
  publicPath: process.env.NODE_ENV === 'production' ? './' : '/',

  // hash 路由：服务端只需回退到 index.html（daemon 静态透传零改动即可用）
  history: { type: 'hash' },

  // 多 chunk 场景下 esbuild 压缩 helper 命名冲突防护（构建器校验项）
  esbuildMinifyIIFE: true,

  routes,

  // 开发期代理到 fenixd daemon；build 后同源直连 /api，无需代理
  proxy: proxy.dev,

  layout: {
    locale: false,
    ...defaultSettings,
  },

  antd: {},

  // add-session-composer 3.3：viewport meta 源头追加 interactive-widget=resizes-content
  // （Android Chrome 键盘压缩布局视口，D4 双轨的 meta 侧）。config 原无 metas
  // 字段（dist viewport 来自 umi 内置默认），同名 meta 须给完整 content——
  // 相比 umi 内置默认去掉 user-scalable=no 与 maximum/minimum-scale 锁定
  // （完全禁缩放违反 WCAG 1.4.4，键盘视口问题由 resizes-content 单独解决）；
  // 构建后须确认产物仅一条 viewport meta。
  metas: [
    {
      name: 'viewport',
      content: 'width=device-width, initial-scale=1.0, interactive-widget=resizes-content',
    },
  ],

  // Tailwind 不走 umi 插件（其 webpack 预加载器在生产构建引发 React #310 崩溃），
  // 改用 tailwindcss CLI 独立生成 src/components/claude-msg/tailwind.gen.css
  // （package.json build 前自动再生成），入口 tailwind.css 不含 base 层不影响 antd。

  // 全局初始数据流：getInitialState 拉取项目列表供侧边栏二级菜单使用
  // （initialState 依赖 model 插件）
  model: {},
  initialState: {},

  // 关闭内置 mock：开发期用 proxy 直连真实 daemon
  mock: false,
});
