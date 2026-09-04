# Tasks: 修复 add-dashboard-spec-doc-tabs-and-info-clear 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/add-dashboard-spec-doc-tabs-and-info-clear/verification-report.md`，定位「真实产品 Bug」的根因并修复

  > 注：父 SPEC 的 `verification-report.md` 在仓库中不存在，仅有 `.fenix/verify-progress/add-dashboard-spec-doc-tabs-and-info-clear/test_scenarios.json` 场景集（摘要称「16 场景，1 个 BUG：scenario 13 `clear-failure-shows-error`」）。经在真实运行中的 Dashboard（8787）上按场景定义复现 scenario 13：清除失败 UI 正确（按钮显示「清除失败」、信息子行保持、不跳转详情），其失败断言 `element_not_exist .page-title` 与 `no_console_error` 属**伪失败**（项目视图头部恒有 `.page-title`；有意 mock 的 404 触发浏览器级 console error，而该场景 `external_net_errors_ok=False` 自相矛盾）。
  >
  > 在父 SPEC 引入的文档弹窗（`docmodal`）代码中定位到一处**真实产品缺陷**：`core/dashboard/static/app.js` 末尾的全局 `keydown` 处理器在按下 Escape 时调用 `closeRunModal()`（运行弹窗）而非 `closeDocModal()`（文档弹窗）。文档弹窗由本 SPEC 新增，因此打开文档弹窗后按 Escape 实际关闭的是错误的弹窗。已修复为 `closeDocModal()`，并在独立端口（8902）的 Dashboard 实例上验证：打开文档弹窗后按 Escape 正确关闭 `docmodal`，且 `runmodal` 不受影响（其自身仍通过遮罩点击 / 关闭按钮关闭）。

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过

  > 本仓库为纯 Python 框架 + 内联静态前端（无 `package.json` / `tsc` / `vite`，Dashboard 静态资源 `app.js` / `style.css` / `index.html` 直接由服务端提供，无构建步骤）。该任务为模板遗留的伪任务，不适用；前端改动已通过浏览器端到端复现验证。

- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归

  > 实际可执行测试为 `python3 -m pytest .`（`.fenix/tests/` 在本仓库不存在）：**424 passed**（含 `tests/test_dashboard.py` 105 passed），无回归。

- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包

  > 已执行，生成 `dist/fenixd-20260827.tar.gz`（276K）。
