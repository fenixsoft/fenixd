# Design: fix-verify-verdict-run-attribution

## Context

verdict 消费链（`core/pm_engine/verification/legacy.py`）：verify 完成后 `_read_verdict` 读 `.fenix/verify-progress/<spec>/.fenix-run-result.json`（旧版 verifier 确定性产物路径，回退主树共享文件须过 role/spec 戳），status 白名单外或 run_id 陈旧时走 stale/foreign 护栏——`_redispatch_fresh_verify` 单点收敛（code-review 842cfc9b4447）复位状态并整轮重派。该文件同时是 in-chain planner（阶段 1 生成场景，cwd 即 verify-progress/<spec>/）的完成产物落点，写入形态 `{"status": "plan-ready", "spec": ...}` 无 run 维度标识。

事故实证（add-command-center，2026-10-26）：文件残留 17:23 的 plan-ready；两轮 verify 完成（18:57、20:45 各 39 分钟、16/18 pass、发现 BUG-1 major）消费时均命中「未知状态 + 陈旧 mtime」→ 两轮整轮作废重派，第二轮后连续争议冻结。report.json 本身留存于进度页属侥幸，verdict 断链导致 fix 链从未接手。

## Goals / Non-Goals

**Goals:**
- 跨 run 残留永不作为本轮 verdict 输入（归属判据：role=verifier + run_id 一致）
- 当轮成果（report.json）在重派丢弃前强制保全留痕
- 最坏情况从「静默扔 39 分钟验证」变为「诚实 blocked + 成果已保全」

**Non-Goals:**
- 不改 agent 侧写 verdict 的 prompt 协议（agent 如何被指示写文件不在本 SPEC 范围）
- 不改为 per-run 独立 verdict 文件路径（保留单文件 + 戳隔离，避免读端全量改路径的扩散面）
- 不禁止 in-chain planner 写 plan-ready 到共享文件（既有行为，判据天然隔离）
- 不动新三阶段管线的阶段 3 消费语义（守卫若位于共享读取单点则自然受益，不另接线）

## Decisions

- **D1 戳结构与预写时机**：`{"run_id", "role": "verifier", "spec", "status": "dispatched"}` 四键；预写在 verify 派发单点（engine.py「Dispatching verifier」处），原子写（tmp+rename），OSError 仅 WARNING 不阻断派发。预写后「残留」只能在派发窗口内出现，消费时残留即异常态。
- **D2 采信判据单点**：收敛在 verdict 读取守卫（legacy.py `_read_verdict` 及其 stale 判定段）。判据：role=verifier 且 run_id=当前消费 run 且 status 白名单内 → 采信；role 缺失或非 verifier / run_id 不符 / status=dispatched → 「本轮无裁决」：先归档 `.stale-<ts>`（保留法证现场），再走既有 fail-closed（blocked + critical 告警）。关键语义修正：run_id 不符从「stale/foreign 重放（丢弃当轮成果）」改为「本轮无裁决（当轮成果按 D4 保全）」——错误归因是本次 39 分钟×2 浪费的直接根因。
- **D3 in-chain planner 写入隔离**：planner 的 plan-ready 无 role=verifier，判据天然不采信；无需 planner 侧改动。
- **D4 保全挂重派收敛点**：`_redispatch_fresh_verify` 内、状态复位前检查 report.json mtime ≥ 本轮 verify 派发时刻（派发时刻取本轮 run 记录的启动时间），命中则重命名 `report-<run_id>.json` + WARNING + 升级告警文案附路径。告警走既有 human-escalation-alert 通道。
- **D5 时间基准**：mtime 比较统一用 stat 取出的 UTC 时间戳与 run 启动时间（ISO8601 UTC）对齐比较，避免 naive/aware 混比（全链 UTC 口径既有约定）。

## Risks / Trade-offs

- **agent 未写 verdict 的频率若升高**：修复后这类轮次从「误判重放重派」变为「blocked 转人工」——若 legacy 降级通道本身高频失写，人工量会上升；由 fix-worktree-lock-release-degrade-gate（降级前置门）从源头压降 legacy 使用频率，两 SPEC 互补。
- **归档文件堆积**：`.stale-<ts>` 备份无人清理；量级极低（仅异常态产生），不做清理机制，观察后必要时并入 runs 清理策略。
- **mtime 精度**：同秒内派发+完成的极端场景可能误判新鲜；影响仅「多保全一份」，无损正确性。
