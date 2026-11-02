## Context
- 收集点：core/self_review.py _collect_run_files :547-567，555（当前目录）与 562（归档目录）两处 glob("*.jsonl")，p.stem 当 run_id。
- 既有判式：core/agent_runner/liveness.py:171-184 _is_dsh_events_dump（stem.endswith('.dsh-events')）已被 liveness/run_files/dashboard runs 三处消费。
- 分类链：伪 run_id 尾 3 行无终态→_reconcile_running_run（:946）查无指标→stale。

## Goals / Non-Goals
- Goals：一处后缀过滤+契约测试，恢复 stale 桶信号纯度。
- Non-Goals：不改伴随流的写侧（dsh_adapter 落盘照旧）；不改 stale 桶语义与对账逻辑（evo-fix-self-review-phantom-running 辖区）。

## Design
- 在 _collect_run_files 合并点统一过滤 p.stem.endswith('.dsh-events')（与 liveness 判式同语义，本地实现或复用导入），两处 glob 一次覆盖。
- 伴随流仍可作后续深扫证据源（文件不动，仅不入 run 统计）。

## Risks / Trade-offs
- 极低：判式已有三处消费先例，无误伤面；契约测试钉死防回退。