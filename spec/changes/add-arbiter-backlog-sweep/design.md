## Context

`add-arbiter-lane` 触发面为事件驱动（两咽喉层），存量冻结（事件已流过）吃不到。本 SPEC（fast-track 跟进，depends_on add-arbiter-lane）补启用时一次性存量回扫。首例处置对象：`evo-refine-midflight-outlier-dims`（10-30 冻结，白名单①类原型案，含 pending 升级告警）。

## Goals

Arbiter 上线即消化历史冻结欠账，不留「上线前冻结永久等人」的死角。

## Decisions

1. **回扫时机**：daemon 启动后一次 + config 热更新 disabled→enabled 跃迁时一次（每进程生命周期内每条跃迁至多一次，防循环）。
2. **判据**：`frozen=true` ∧ 存在同 spec 未处理（pending）机器升级告警——以 freeze_for_human「冻结+告警成对」语义反查，天然排除人工冻结（`freeze_spec` 不产告警对）；`frozen_until` 非空（定时冻结）显式排除。
3. **复用管线**：命中者走 add-arbiter-lane 既有 dedup/单飞/预算管线，不建第二套派发路径；幂等靠同签名 dedup，不另记回扫簿。
4. **顺序保证**：depends_on add-arbiter-lane——本 SPEC 派发时 `core/pm_engine/arbiter.py` 已在 main，故声明 `kind: modify`。
5. **生效**：合并后需重启加载，交付 restart_request 信号（supervisor 消费）——父 SPEC 的重启先于本 SPEC 派发发生，不共享。

## Risks

- 回扫面告警被 150 条裁剪截断的极旧冻结会漏扫——语义可接受（裁剪最旧历史不影响语义是既有纪律），且此类冻结早已超出处置时效。
- 回扫一次性派发多存量时受单飞队列串行约束，处置节奏自限，无风暴风险。

## 界面约束

无 UI 改动。
