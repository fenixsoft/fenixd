# Tasks: 修复 v2-shell-hash-router 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/v2-shell-hash-router/verification-report.md`（实际位于 `.fenix/verify-progress/v2-shell-hash-router/.fenix-run-result.json`），定位「真实产品 Bug」的根因并修复
  - 【严重】hash 路由断裂：app.json 平铺 pages 不生成侧边导航 → 改为 children 分组；导航 `<a href="/overview">` history 链接 → app.js 渲染后改写为 `#/overview`，jumpTo 统一写 hash，hashchange 同步 embed
  - 【轻微】Font Awesome webfont 404 → 补齐 `v2/thirds/@fortawesome/fontawesome-free/webfonts/`（woff2）并入包
  - 回归：tests/v2/verify-fix.spec.js 按 10 个验证场景逐条断言（10/10 通过）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（N/A：本仓库为 Python + 原生静态 JS，无 npm/tsc/vite 构建；以 Playwright 冒烟 + verify-fix 场景测试替代）
- [x] 2.2 运行框架单元测试确认无回归（`.fenix/tests/` 不存在，实际路径为 `tests/`：`python3 -m pytest tests/ -q`，766 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260829.tar.gz，已确认含 v2/thirds 字体）
