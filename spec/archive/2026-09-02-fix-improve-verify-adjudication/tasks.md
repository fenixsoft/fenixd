# Tasks: 修复 improve-verify-adjudication 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/improve-verify-adjudication/verification-report.md`，定位「真实产品 Bug」的根因并修复

### 根因分析与修复结论

验证报告列出 4 项真实产品缺陷（Bug #1~#4），全部位于 Dashboard 前端渲染层
（`core/dashboard/static/app.js` + `style.css`）。经 Playwright 真实浏览器复现
（启动 DashboardHTTPServer + 真实点击/切换页签 + 模拟 SSE `detail` 增量推送），
逐一定位并确认已修复：

- **Bug #1（major）详情页 `.scenario.fail` / `.bug-card` 在失败场景下未渲染**
  根因：详情页用 morphdom 增量更新 `#main`，旧 `onBeforeElUpdated` 守卫
  `if (fromEl.id === 'tl-root') return false` 在「时间轴页签 → 场景/Bug 页签」
  切换时会**跳过更新 `#tl-root`**，导致旧时间轴 DOM 残留在场景/Bug 分支位置，
  新 `.scenario.fail` / `.bug-card` 卡片挂载失败。
  修复：守卫收紧为 `if (fromEl.id === 'tl-root' && toEl.id === 'tl-root') return false`，
  仅当新旧节点都是同一时间轴根才交给 React 托管；切离时间轴页签时正常 morph
  场景/Bug 卡片（renderView / renderSpecInPlace 三处一致）。

- **Bug #2（major）告警项 / 处理按钮被 CSS 隐藏**
  根因：告警横幅默认折叠列表（`alert-list` 带 `hidden`）。存在未处理升级时，
  `.alert-item` 与 `.alert-handled-btn` 虽在 DOM 中但不可见，管理员无法处置。
  修复：`renderAlertBanner` 默认展开列表（`expanded = !oldList || !hidden`），
  使告警项与「标记已处理」按钮对管理员可见可交互。

- **Bug #3（major）信息子行「清除」点击后 `.spec-info-row` 残留**
  根因：POST `/api/spec-error-clear` 成功后仅依赖 watcher/轮询刷新，清除后
  子行残留。修复：成功后立即 `btn.closest('.spec-info-row').remove()` 主动移除，
  并触发一次列表刷新与 STATE.md 保持一致。

- **Bug #4（minor）场景结果空状态文案与 SPEC 语义不符**
  根因：空状态统一显示「暂无运行时间轴」，未区分 report.json 损坏/不可读与
  真正的无场景结果。修复：按 `d.report.error` 区分——
  `report.json 损坏或不可读` / `暂无场景结果`（renderSpec 占位分支与
  renderScenarios 损坏分支一致）。

复现验证（真实浏览器）：场景结果页签 `.scenario.fail`+`.assertion.bad` 可见、
Bug 列表 `.bug-card`+`.bug-evidence` 可见、告警项与处理按钮 `hidden=False`、
清除后 `.spec-info-row` 消失、空状态文案正确；SSE `detail` 增量推送后卡片不丢。

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过
      - 注：Dashboard 为原生 JS（无 tsc/vite 构建步骤），前端改动直接生效；
        已用 `python3 -m pytest tests/test_dashboard.py`（110 passed）与
        全量 `tests/`（586 passed）确认无回归。
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
      - 注：`.fenix/tests/` 为空，框架单测即 `tests/`（586 passed）。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
      - 已生成 `dist/fenixd-20260828.tar.gz`（316K）。
