# 提案：晋升 lint 一次全报与 tasks.md 变化即时唤醒

## 背景与问题

人工立项车道（用户主树活交互会话直接起草 spec）的 tasks.md 格式失误，每次都要付 40 分钟量级管线延迟。已发生损失（两窗同族、量化）：

- 本窗实例 fix-windows-review-longtail：15:25:42Z 第一次 promotion lint 拒收（未解析出任务分组）→ 15:37:41Z 恢复节拍重触发后第二次拒收（7 分组/18 条任务行缺编号）→ 15:53:52Z 用户修复提交（31ea143e6）→ 16:07:42Z 才被 30 分钟 full scan 自动晋升，立项到晋升 42.0 分钟、修复落盘后空等 13.8 分钟（fenixd.log:13279/13285/13287/13301 逐度核实）。
- 2026-11-06#可改进#1：mobile spec 晋升延迟 44 分钟（同族：lint 拒收 + 30 分钟节拍兜底），至今无承接。

根因三层中两层可修：①lint 报错一次只报一类（core/deliverables.py lint_tasks_text :3293 三段互斥早退，分组不可解析时任务行编号检查结构性空集，但 checkbox 总数 item_count 恒可测）；②修复落盘无即时晋升唤醒（core/event_bus.py _watch_loop :1062 每 2 秒只对 STATE.md 做 checksum，人工改 tasks.md 不触碰 STATE.md，只能等 30 分钟 full scan）。写侧格式不熟一层不修——守卫按设计工作（两拒一过零漏网，防住了缺编号任务行被下游静默丢弃）。

## 目标

1. lint 一次全报：tasks.md 分组不可解析时，违规消息并列披露 item_count 与「分组修正后任务行还需补组号.序号编号」提示，人工一轮修完两处。
2. tasks.md 变化即时唤醒：对 status=drafted 且 STATE error 为 tasks.md lint 文案的 spec，tasks.md 文件变化时即时重评晋升（复用 spec_drafted 恢复出口，继承 start_after 门与 promote_mode 短路），把 30 分钟节拍恢复缩到秒级。
3. 清错留痕：dashboard 清除错误端点清空 STATE error 时显式留痕（当前 dashboard 独立进程的留痕不汇入 daemon 日志，15:53:52Z 的无日志清空即此缺口）。

## 非目标

- 不放宽 lint 判据本身（可解析性硬门与编号规则保持）。
- 不改 30 分钟 full scan 兜底节拍（即时唤醒是叠加通道，兜底保留）。
- 不处理程序化起草车道（fenix-new/evo/CLI 已有 scheduling_kick 等通道，本 SPEC 只补人工车道盲区）。
- 不覆盖 error 为 Deliverables/中文标题单族 lint 文案的 drafted spec 的即时唤醒（唤醒名单按 tasks.md lint 短语匹配，这两族修复落盘仍走 30 分钟兜底节拍；如需同款提速另行立项承接）。

## 与存量的关系

- 无同主题在途或近期归档；在途 add-spec-title-promotion-gate 同在 promotion.py 落点（中文标题存在性门），落地时须注意同文件碰撞面与先后顺序。
- 知识页 draft-promotion-gate.md 记载三类 lint 与 30 分钟周期重试，未覆盖本 SPEC 两点；落地后经知识回填通道补记。
- 即时唤醒复用既有恢复出口与「→testing 跃迁即时派发」先例（event_bus _dispatch_changes :1365-1383），不新发明事件类型。
