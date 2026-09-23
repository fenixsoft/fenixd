# 交接登记（来自 add-project-detail-tabs）

> 本文件由 `add-project-detail-tabs`（fast-track 实现轮）于 2026-09-19 登记。
> 该变更已把本 SPEC 的会话界面承载形态改为新形态（见下），后续/回归轮 MUST
> 改道对应 web 场景（详见 `.fenix/verify-progress/add-dashboard-live-session/
> handoff-add-project-detail-tabs.md`），MUST NOT 原样重跑。

## 承载形态变更

1. 项目页标题栏右端「接入会话」按钮已移除（header 恢复为项目名 + SPEC 计数）。
2. 会话界面由全屏 Modal（`SessionModal.tsx`，已删除）迁移为项目页「会话」分面
   的内联面板（`SessionPanel.tsx`），会话行为契约零变更。
3. 终态文案改写为「会话已结束。切离本分面再切回可开始新会话。」（Modal 的
   「关闭/重新打开」操作已不存在）。
4. 切离分面释放 SSE watch 订阅但不终止会话进程；分面未选中时零会话请求。

## 需改道的 Modal 形态 web 场景（6 条）

`web-entry-button-visible`（按钮已移除）、`web-modal-title-project`（Modal 标题
不存在）、`web-open-modal-empty-state`（空态保留但容器为分面）、`web-start-session`
（手动启动语义不变、容器为分面）、`web-reopen-modal-reconnect`（对应「切离分面
再切回接回」）、`web-stop-session`（终态文案已改写）。
