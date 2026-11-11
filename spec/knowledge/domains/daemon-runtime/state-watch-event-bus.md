<!-- knowledge: capability=state-watch-event-bus rev=2 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 状态监视事件总线

`core/event_bus.py` 监视 `STATE.md` 变化并把内部事件派发给 PM Engine，是 daemon 感知状态变更的主通道。

## 现行规则

- 监视对象是 `STATE.md` 文件本身：变化检测是固定 2 秒间隔的轮询 + checksum 比对（`_watch_loop`），实现内无任何 inotify 依赖，纯轮询口径跨平台可用。
- 除增量事件外保留周期性全量扫描兜底，漏掉的事件由全量扫描补齐。
- 依赖闸门「接受态」单源：EventBus 与 `PMEngine._dependencies_satisfied` 共用 `DEPENDENCY_ACCEPTED_STATUSES` 常量，禁止两处各写一套口径。
- 可选挂接 hook 分发回调（`HookEngine.dispatch`），状态事件可外溢为钩子。
- admin run id 归属判定按「epoch 段 ≥10 位数字锚定边界 + spec 段全等比较」，不用前缀匹配——spec 名互为前缀时不允许把 `admin-<spec>-2` 的 run 记到 `<spec>` 头上。
- 事件派发失败不得吞掉状态变更事实：全量扫描兜底保证最终一致。

## 代码锚点

- 主实现：`core/event_bus.py`（`_watch_loop` 轮询与 checksum 比对、`_periodic_scan_loop` 全量扫描兜底）

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
- 2026-11-11 posix-dependency-true-distribution-1110（spec/knowledge/_inbox/done/posix-dependency-true-distribution-1110.md） — 修正变化检测规则：明确为固定 2 秒间隔轮询 + checksum 比对、实现内无 inotify（删除「Linux 上可选 inotify」失实措辞）；补代码锚点段。注：本页 origin=prehistoric，marker sources 仅接受 git 区间锚点，本轮溯源以本行为准未追加 done/ 路径
