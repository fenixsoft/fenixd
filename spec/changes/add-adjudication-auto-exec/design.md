## Context

redesign-chain-panel-ui 事故（2026-11-11）暴露升级处置链终点的结构性空转：arbiter 完成完整调查并产出明确推荐后，pending 人工告警无限期等待，实际等待 8.4h 且人工点击信息量为 0。现状架构事实：

- 告警本体存 `.fenix/admin_alerts.json`，记录不可变，handled 状态读时合并（core/dashboard/data/admin_alerts.py）。
- choice 执行已有单机器：`core/admin_choice_exec.py::execute_choice_for_disposition(project_root, signal, disp, logger)`，人工 alert-resolve（admin_actions.py:3074 `execute_adjudication_choice`）与链 closed 出口共用，「三处同源禁复制」既有纪律。
- choice 注册表为纯静态声明（core/dashboard/data/adjudication_choices.py），按 signal_type 映射，`recommended_action` 字段已有先例。
- daemon 侧调度面：2s watch（checksum 轮询）、60s 精触发（仅 ready 态）、30min full_scan 兜底（`_recover_testing` 含无驱动判定 spec_is_undriven，与在飞 Administrator run 互斥）。
- 升级链链序 Admin→Arbiter→人工为固定不变式，本设计不改链序。

## Goals / Non-Goals

**Goals:**

- pending 升级告警在「推荐明确 + 动作可逆自限 + 判据满足」时于 grace 窗后自动执行，处理延迟 10h36m → ≤32min
- 人工否决/改选在 grace 窗内始终优先（先到先得）
- 自动执行留痕与人工点击同构、dashboard 可审计、不静默
- testing 跃迁外部直写后即时派发（秒级），消除 30min 兜底延迟
- human-only 档（state-advance/terminal）不受影响，但获得老化升级可见性

**Non-Goals:**

- 不改变链序、白名单调查语义、复现配额
- 不自动执行 state-advance / terminal 档动作
- 不做告警外推推送（wechat 桥接属 DSH 侧，另行接线）
- 不改人工 alert-resolve API 契约

## Decisions

1. **风险档位收敛在静态注册表单源**。risk_tier 作为 choice 条目字段落在 adjudication_choices.py，历史条目缺档按最保守 `terminal` 兜底（不自动执行）。*备选*：告警发射时逐条拷贝档位 → 弃，违反三处同源禁复制，漂移风险高。

2. **策略引擎 = daemon 侧新增模块 + 60s 轻量扫描环**。新模块（core/admin_auto_exec.py）每 60s 读 pending 告警做廉价判定（文件读 + 内存判据），到点执行。*备选 A*：挂 30min full_scan → grace 30min 实际延迟最坏 60min，价值折半，弃；*备选 B*：挂 dashboard 进程 → dashboard 非常驻，daemon 才是权威，弃；*备选 C*：逐告警定时器 → 复杂度不值，弃。

3. **执行复用既有单机器**，新增 actor=auto-policy 的 disposition 留痕形态，与人工/链出口同构。三处同源扩展为四处同源，禁止第四份复制逻辑。

4. **grace 窗状态不落盘**：到期时刻 = created_at + grace（缺省 30min，单源 core/config.py 签名常量），读时计算。窗内人工动作（resolve 任一 choice 或 mark handled）先到先得；引擎执行前瞬时重读 handled 与判据，二次确认后执行。

5. **自动执行判据**（全部满足才执行，缺一跳过并记日志）：
   - 该告警关联 arbiter 完整调查 ≥1 次且有明确推荐 choice（链状态/处置叙事中记录的 recommendation）
   - 推荐 choice 的 risk_tier = reversible-experiment
   - 同 spec 无共存更高风险档 pending 告警
   - 本 spec 连续 auto-exec 计数 < 上限（缺省 2，config 单源；计数从处置留痕按 actor 派生，不新增状态文件）

6. **testing 即时派发走既有恢复路径，不新增事件类型**：`_dispatch_changes` 检测到 `→testing` 跃迁且无驱动判定命中时，直接调用 `_recover_testing` 等价的 re-trigger 逻辑。幂等由 spec_is_undriven + 在飞互斥既有语义吸收。*备选*：新增 spec_testing 事件类型 → 需 PMEngine 全链路适配，改动面大收益同，弃。派发失败时 30min full_scan 仍是重试网（见 Risks）。

7. **fail-open**：策略引擎任何异常单条捕获、记日志、本轮跳过；引擎永不阻塞其他车道；config 开关 `auto_exec.enabled`（缺省 true）可一键降级为纯人工。

8. **human-only 老化升级**：策略引擎扫描时对超阈值（2h/6h 两档）pending 的 human-only 告警写升级活动记录（dashboard 高可见度），只做可见性不做动作。

## Risks / Trade-offs

- [引擎误执行错误推荐] → 仅 reversible 档（自限：失败自然再冻结再告警，最坏一轮验证算力）+ 判据五重 + grace 可否决 + 留痕可审计。
- [算力烧损循环] → 连续 auto-exec ≤2，超限强制人工；重验失败会再冻结再走 arbiter，形成天然节流。
- [人工点击与引擎到点竞态双执行] → 引擎执行前瞬时重读 handled + 判据；处置留痕幂等键（signal+choice+actor 窗口内查重）；残余竞态窗口秒级，后果为一次冗余自限动作，可接受。
- [testing 即时派发与既有车道重复派 verify] → 无驱动判定排除在飞 Administrator run（recovery-path-liveness 既有语义）；watch 通道与 60s/30min 兜底互为重试网。
- [watch 通道跃迁只发一次、派发即失败无即时重试] → 接受：full_scan 30min 内兜底，与现状相比仍是净改善。
- [risk_tier 缺档误放行] → 缺档一律 terminal 兜底（不自动执行），保守方向安全。

## Migration Plan

1. 注册表条目补 risk_tier（静态声明，无数据迁移）；缺档兜底保证旧数据安全。
2. 策略引擎 + 开关随 daemon 重启生效；`auto_exec.enabled=false` 即回退纯人工语义。
3. testing 派发为 event_bus 内局部扩展，回滚 = 还原映射处改动。
4. 全程无 schema 迁移、无外部依赖新增。

## Open Questions

- 告警记录当前是否携带结构化 severity 字段供「共存更高档」判定，还是需从 signal_type 推导？（实现期核实，倾向后者）
- 老化升级的活动记录落点（admin_activities vs 叙事 sidecar）实现期定。
