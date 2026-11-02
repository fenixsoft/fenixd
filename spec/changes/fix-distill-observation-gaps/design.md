# Design: fix-distill-observation-gaps

## Context

add-distill-run-artifacts 落地后的首次真实批次端到端（2026-11-02 fenix-prototype 时效归档触发）暴露两个缺陷，均属「验证夹具与生产形态错位」类盲区：

1. **聚合剔除误吞**：`aggregate_org`（command_center.py:543-546）按 `STATE.archive.md` 归档清单剔除「已归档 SPEC 名下」的 run——语义是剔除完结 SPEC 的实现过程 run（impl/review/verify），但蒸馏 run 的 spec 段恒为已归档 SPEC 名（蒸馏由归档/交付触发），天然命中剔除。验证时伪造产物的 spec 段不在归档清单，Scenario 假绿。实证：fenix-prototype 批 done 终态 + get_runs 正确返回，卡片 runs=0。
2. **无心跳 stale 误判**：合成产物仅批开始/收尾两个写点，spawn 超过 1800s（`_RUN_STALE_SECONDS`）即末行非终态+停更超时 → stale → `runs_retention_check` 移入 archive → 批收尾终态行 fail-open 写空（文件已不在原路径）。实证：fix-frozen-scenario 批（bigmodel stall 慢跑 30 分钟超时 give_up）产物停 started、error 终态丢失、pending 台账滞留。

## Goals / Non-Goals

**Goals**

- 蒸馏 run 在指挥中心全窗口径可见（真实批次、真实成功率）
- 长跑批不再被判 stale，超时/失败终态如实落盘

**Non-Goals**

- 不回填历史失真产物（用户已定调不回填；archive/ 里停 started 的旧产物由天龄兜底自然清理）
- 不动剔除规则本体语义（其余 lane 行为不变）
- 不给蒸馏 run 补 run_metrics 指标（维持 add-distill-run-artifacts Non-Goals 口径）

## Decisions

### D1：剔除豁免在剔除点内联，不重排序

现行代码顺序：取 `r.get("spec")` 判剔除（:545）→ 取 raw agent_type 归一 lane（:547-548）。豁免改为在剔除条件内先取 raw agent_type：

```python
raw_lane = r.get("agent_type") or "agent"
if archived_names and raw_lane != "knowledge-distiller" and str(r.get("spec") or "") in archived_names:
    continue
```

后续 `raw_lane` 复用（消除重复取值），LANE_ALIASES 归一逻辑与位置不动。备选（否决）：把剔除整体挪到 lane 归一之后按 lane 判断——重排序会改变「其他」分区的观测 lane 收集时机（归档名 run 原本进不了 lane 统计，挪后蒸馏外的未知归档名 lane 会冒出「其他」卡），行为面扩大不可控；内联条件是唯一最小改动。

### D2：心跳=后台 daemon 线程定期 append（仿 planner throttled-wait 心跳语义）

`_run_batch` 批开始（首个 spawn 前）启动心跳线程：`interval = _DISTILL_HEARTBEAT_SECONDS = 900`（stale 阈值 1800s 的一半，两次心跳窗口内必有写入；既不密到污染产物也不松到撞 stale）；线程循环 `append_run_line(run_file, {"type": "heartbeat", "timestamp": ...})`，`threading.Event.wait(interval)` 支持立即停；批收尾 `finally` 中 `event.set() + thread.join(timeout)` 后写终态行（保证终态行为末行）。

- `type: "heartbeat"` 不在 `_RUN_TERMINAL_STATUS_MAP` → classify_run 判 running（在飞语义正确）；`strip_run_id_suffixes`/run_spec_part/时间线读侧不解析行内容，零影响。
- 心跳行与批开始行同 fail-open 口径（try/except OSError 吞掉）。
- 备选（否决）：spawn 期间同步轮询写心跳（改 `_spawn_and_wait` communicate 为轮询）——侵入 one_shot harness 契约，风险远大于收益。

### D3：线程生命周期与异常安全

线程用 `try/finally` 包住批执行体的既有结构扩展：现有 `finally`（终态行写入）之前完成 `event.set(); thread.join(timeout=5)`——任何 return 路径（成功/give_up/提交失败滞留）线程都收敛；线程体内全捕获异常（OSError 静默、其余异常也吞——心跳是纯观测，绝不让观测线程杀死蒸馏批）。批函数抛异常路径：`_run_batch` 外层 `_worker` 已有批级 try/except，finally 收敛线程即可覆盖。

## Risks / Trade-offs

- **[心跳行增大产物体积/读侧噪声]** → 900s 间隔 × 30 分钟超时上限 ≈ 每批 ≤3 行，可忽略；`_read_run_lines(max_lines=3)` 只读尾窗。
- **[豁免后蒸馏 run 的 cost 聚合尝试读产物尾窗]** → 无 usage 产物 cost=None 不贡献（既有 None 透传口径），零额外开销面。
- **[join timeout 5s 内线程未死（极端 IO 卡顿）]** → 线程是 daemon 线程（`daemon=True`），进程退出不阻塞；下一批的产物是不同文件，残留线程最坏多写一行到已收尾文件（append 语义无害，终态行其后仍可能是末行……严格说终态行先写、心跳后写会翻末行——join timeout 后若线程仍活着，跳过终态行写入改为先 set 再等？否决复杂化：Event.set 后 wait 打断，循环条件退出，5s 内必停；把 join timeout 提为 10s 并在终态行写入前完成 join，顺序保证终态行为末行）。

## Migration Plan

纯行为修正，无迁移；回滚 = revert 两处（豁免条件 + 心跳线程），产物形态兼容（多余心跳行不破坏读侧）。

## Open Questions

无。
