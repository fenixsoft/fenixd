<!-- knowledge: capability=state-watch-event-bus rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 状态监视事件总线

`core/event_bus.py` 监视 `STATE.md` 变化并把内部事件派发给 PM Engine，是 daemon 感知状态变更的主通道。

## 现行规则

- 监视对象是 `STATE.md` 文件本身：变化检测以轮询 + checksum 比对为基础（跨平台可用），Linux 上可选 inotify。
- 除增量事件外保留周期性全量扫描兜底，漏掉的事件由全量扫描补齐。
- 依赖闸门「接受态」单源：EventBus 与 `PMEngine._dependencies_satisfied` 共用 `DEPENDENCY_ACCEPTED_STATUSES` 常量，禁止两处各写一套口径。
- 可选挂接 hook 分发回调（`HookEngine.dispatch`），状态事件可外溢为钩子。
- admin run id 归属判定按「epoch 段 ≥10 位数字锚定边界 + spec 段全等比较」，不用前缀匹配——spec 名互为前缀时不允许把 `admin-<spec>-2` 的 run 记到 `<spec>` 头上。
- 事件派发失败不得吞掉状态变更事实：全量扫描兜底保证最终一致。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
