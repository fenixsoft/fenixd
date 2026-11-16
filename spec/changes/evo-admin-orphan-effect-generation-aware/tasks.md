## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin_monitor_orphan_effect.py
  kind: new
```

## 1. 生效核查代际感知

- [x] 1.1 core/admin_monitor.py：_orphan_group_effect_evidence 在 STATE frozen=True 判 False 分支内增加「处置组完成时刻之后该 spec 的合法推进轨迹」核查；代际锚点=组内最新记录 created 时刻（处置记录无独立终态时间字段，与 grace 门 ③ max(created) 同口径）。轨迹匹配契约（MUST NOT 逐字复用解冻族匹配谓词 _ORPHAN_UNFREEZE_TRANSITION_RE 与 deliberate-channel 过滤）：`Transition:` 与 `Gate transition:` 两族成功行前缀都认（testing→verified 走前者 channel=auto；复位直通道 blocked→testing 走后者 channel=recovery）、from→to 须属合法迁移、spec 名精确锚定本组、行时间戳落在 [锚点, now]、channel 不限（auto/manual/recovery）；仅读面（尾部限量/轮转候选集/mtime 剪枝）复用 _read_recent_unfreeze_transitions 同款。命中判「已生效、被新代际取代」；轨迹缺失或日志不可用维持现行 fail-closed 升级语义零变化
- [x] 1.2 core/admin_monitor.py：消解簿记——旧处置组转记已消解终态留痕（附轨迹证据行引用，不带 escalate=true）；旧组关联 SIGNAL 记录 mark_signal_handled 收口（⑦ 分支同款出口，兼作扫描 ④ 门回环抑制）；新代际信号条目使用独立于旧组 sig_type 的类型键、经 store append 通道落账、开立即终态/handled 留痕形态（不进未处理人工告警面、不触发人工升级或仲裁调查）、携带旧处置组引用与轨迹证据行引用

## 2. 测试

- [x] 2.1 tests/test_admin_monitor_orphan_effect.py：三态锚定——处置后合法前移再冻结判已生效不升级且回链新代际；处置真未生效（处置完成后无轨迹）仍升级人工；日志轮转缺失 fail-closed 仍升级
- [x] 2.2 tests/test_admin_monitor_orphan_effect.py：轨迹匹配与时序门——`Gate transition:` 复位行（channel=recovery）与普通 `Transition:` verified 行（channel=auto）均被识别；时间戳早于处置组完成锚点的轨迹不命中；Cannot/Invalid/Idempotent/Frozen-stripped 等非成功行不构成轨迹
- [x] 2.3 tests/test_admin_monitor_orphan_effect.py：消解簿记回归锚——已消解组重扫描不再重复转记/重开条目（旧信号已收口、新条目类型键独立于旧 sig_type）；未命中轨迹时旧组行为与现状一致（升级记录文案与 escalate=true 终结记录零漂移）
