# Tasks: 修复 v2-shell-hash-router 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/v2-shell-hash-router/verification-report.md`，定位「真实产品 Bug」的根因并修复

  > 真实产品 Bug 已在父 SPEC 实现提交 `be8f251` 修复且为本分支祖先：(1)【严重】hash 路由断裂——app.json 改为 children 分组渲染侧边导航、app.js 渲染后将导航 history 链接改写为 `#/overview` 风格并统一 jumpTo 写 hash、监听 hashchange 同步 embed；(2)【轻微】webfont 404——补齐 `v2/thirds/@fortawesome` webfont。本任务工作目录代码已含该修复，并以浏览器端到端实渲染验证：访问 `#/overview` 侧边导航含 `a[href='#/overview']`、各参数路由壳渲染正常、无 404 console error、legacy `/` 页 `#main` 正常。验证报告 `report.json` 为修复落地前的陈旧快照（10/10 失败），非当前代码状态。

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过

  > 本仓库为纯 Python 框架 + 内联静态前端（无 `package.json` / `tsc` / `vite`，Dashboard 静态资源 `app.js` / `sdk.js` / `index.html` 直接由服务端提供，无构建步骤）。该任务为模板遗留的伪任务，不适用；前端改动已通过浏览器端到端实渲染验证（见 1.1）。

- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归

  > 实际可执行测试为 `python3 -m pytest tests/`（`.fenix/tests/` 在本仓库不存在）：**775 passed**，无回归（含 `tests/test_dashboard.py`）。

- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包

  > `dist/fenixd-20260829.tar.gz`（2.6M）已生成，内含修复后的 `v2/app.js` / `v2/pages/app.json` 与 `v2/thirds/@fortawesome` webfont。
