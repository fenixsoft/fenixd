## Deliverables

```yaml
- path: core/dashboard/static/src/utils/embedMount.ts
  kind: new
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx
  kind: modify
- path: core/dashboard/static/tests/embedMount.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. API 前缀单点（embedMount.ts）

- [x] 1.1 新增 `core/dashboard/static/src/utils/embedMount.ts`：从 `location.search` 一次性解析并缓存 `apiBase`（缺省 `''`）与 `embed=1` 布尔；导出 `withApiBase(path)`（前缀拼接，含斜杠归一，缺省恒等返回）、`isEmbedMode()`、测试注入口（node 环境无 location，注血后生效）；零 import 保持既有模块形态
- [x] 1.2 `services/dashboard.ts` 接入单点：`request()` 内 fetch 路径经 `withApiBase()`；`export const STREAM_URL = withApiBase('/api/stream')`；`architectureDiagramUrl()` 返回值经 `withApiBase()` 前缀化（架构图 iframe `src` 下发 URL，不经 fetch、不属 STREAM_URL，评审补入）；除上述三处外不得出现其它 `/api/` 直连路径（全文件 grep 自检留痕）
- [x] 1.3 `ClaudeOutputPane.tsx` 硬编码 `new EventSource('/api/stream')` 改引 services 单源 `STREAM_URL`（消除最后一处根相对直连）

## 2. embed 壳层隐藏（app.tsx）

- [x] 2.1 `app.tsx` 运行时布局配置按 `isEmbedMode()` 分支：`menuRender: false` + `headerRender: false`（ProLayout 关闭属性），页面自身内容头不动；非 embed 分支逐字节保持现状（不重排既有配置）

## 3. 前端单测（tests/embedMount.test.mjs）

- [x] 3.1 参数解析与拼接（写入 `core/dashboard/static/tests/embedMount.test.mjs`）：`withApiBase` 缺省恒等、前缀拼接（含多斜杠归一）；`isEmbedMode` 对 `embed=1`/缺省/`embed=0` 的判定；两参数组合互不干扰
- [x] 3.2 缺省行为回归（fetch mock，etagCache.test.mjs 先例）：无参数启动下 `getOverview` 等封装与 `STREAM_URL` 产出与改造前逐字节一致的 URL（含 `architectureDiagramUrl` 缺省产出 `/api/architecture/diagram?...`）
- [x] 3.3 前缀化回归（注血 + 动态 import）：`apiBase=/fenix-dashboard` 下封装调用与 `STREAM_URL` 全部带前缀；`ClaudeOutputPane` 引用单源（源码面 grep 断言无硬编码 `'/api/stream'`）；`architectureDiagramUrl` 产出带前缀的 iframe `src`

## 4. 构建产物重建与全量回归

- [x] 4.1 `cd core/dashboard/static && pnpm build` 重建 `dist/`（产物锚点 dist/index.html，声明为 reference）；确认产物保持 hash 路由 + 相对资源引用形态
- [x] 4.2 `node --test tests/*.test.mjs` 全量回归全绿（含新增 embedMount 用例）；daemon 同源直连冒烟（构建产物在 `:8787` 根路径加载、请求无前缀、SSE 正常）
