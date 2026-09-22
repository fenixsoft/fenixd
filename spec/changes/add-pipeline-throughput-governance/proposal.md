# add-pipeline-throughput-governance 提案

## Why

全历史耗时调查显示**实现排队 893h（37.1%）是最大时间池**：`max_concurrent: 3` 的槽位串行叠加单巨型 spec 垄断（09-16 单 spec 连续 implementing 10.8h，当天 7 个 spec 各等 15-18h）；`done→pushed` P50 仅 14s 但均值 41m——182h 几乎全由 merge 冲突重试与冻结等待贡献（138 次 git 冲突告警）；daemon 重启一次杀掉 3 个在飞 40-70 分钟的 impl run（drain 1800s ≫ supervisor 60s SIGKILL 宽限，结构性错配）；bug-found 修复环 120 次、`bug-found→implemented` P90 12.7h，小缺陷也走整轮 fix SPEC。本 SPEC 目标：提高管道吞吐、把合并与重启的失败模式前置拦截、给小缺陷开轻量通道。

## What Changes

- **并发槽位上调**：`agents.max_concurrent` 代码缺省值（现 2）与 `config.template.yaml` 推荐值统一上调至 5；full-suite.lock 主机级回归锁已保证多 spec 回归互斥（锁等待 600s 上限语义不变）；文档补充并发上调的资源面（worktree 磁盘/网关并发）说明。运行时 `.fenix/config.yaml` 的实际调整为人工运维步骤（写入文档，不进任务门禁）。
- **merge-back 前置预检**：merge 前对「主树 WIP 脏文件集 ∩ 分支触碰文件集」求交，交集非空时不发起 merge，直接走人工升级告警并保持 spec 可重试状态——替代现有「尝试 merge→冲突→autostash→回滚→重试」的失败循环；实现须复用 `core/worktree_manager/mergeback.py` 既有 `_wip_overlap_gate`/`_detect_wip_overlap` 判定（evo-merge-back-wip-overlap-gate 治理已合入代码，`spec/archive/` 无同名归档目录，以代码注释为载体；`core/wip_checkpoint.py` 为锚点提交机制），在其之上统一升级出口，不重复造轮子；本能力有意把 WIP 重叠缺省处置从 auto stash 收纳改为升级拦截（trade-off 见 Impact 风险面）。
- **重启排水保护**：daemon restart 的在飞 run 排水窗口上限改为可配置（`agents.run_drain_max_seconds` 类配置项，缺省 60s、专管 restart 场景、MUST ≤ 既有 `admin.shutdown_drain_seconds`）；现状病根是排水窗口 1800s 过长而非 supervisor 截断（supervisor SIGKILL 等待 = `shutdown_drain_seconds + 120s`，非固定 60s）；restart 触发时向在飞 run 广播 checkpoint 信号（best-effort，促使 implementer 尽快落盘进度声明），超窗强杀路径保留。
- **bug-found 小缺陷轻量通道**：验证轮判定为「单场景失败 + 修复影响面 ≤3 文件 + 无 judge 争议」时，走 code-fix 轻量车道修复并仅重跑该场景及依赖场景，不再派生整轮 fix SPEC 循环；超阈值维持既有 bug-found→fix SPEC 路径。修复后重验与 verdict 缓存（add-verify-lane-throughput）联动但独立可用（直接构造子集场景集执行）。
- **spec-review 打回理由结构化**：评审结果 JSON 新增 `rejection_class` 枚举字段（`format` / `substantive`；缺字段按 unknown 兼容），用于统计与降噪（格式类打回可机械预防）。

## Capabilities

### New Capabilities

- `dispatch-concurrency-tuning`: max_concurrent 缺省与模板推荐值上调、资源互斥前提（full-suite.lock）、可回退性。
- `merge-back-precheck`: merge 前 WIP 重叠预检的判定、升级路径、与既有 overlap-gate 的关系。
- `graceful-restart-drain`: 排水窗口配置化、与 supervisor 宽限的协调规则、checkpoint 广播语义。
- `minor-defect-fastlane`: 小缺陷判定阈值、code-fix 车道承接、子集重验、超阈值回落。
- `spec-review-rejection-schema`: 打回理由分类字段契约与兼容规则。

### Modified Capabilities

（活跃能力 `quality-gates-progress`、`task-progress-phase-display` 不受影响。注意 merge-back-precheck 对既有 merge-back WIP 闸门缺省行为属修改性增量——auto 收纳→升级拦截，见 `merge-back-precheck` 能力说明。）

## Impact

- **调度**：`core/pm_engine/dispatch/queue.py`（并发缺省值）。注意本 SPEC 与 `add-verify-lane-throughput` 均触碰该文件（不同 hunk 区域），并行实现存在 merge-back 小冲突概率，属可自动合并范围。
- **merge-back**：`core/worktree_manager/mergeback.py`（既有 `_wip_overlap_gate`/`_detect_wip_overlap` 之上统一升级出口）、`core/state_machine.py`（merge-back 调用方 `merge_back_from_branch` 于 state_machine.py:1576）、`core/wip_checkpoint.py`（现状复用评估）。
- **重启链路**：`core/config.py`（新配置 `agents.run_drain_max_seconds` 校验/派生，参照既有 `shutdown_drain_seconds` 校验模式）、`core/agent_runner/runner.py`（restart 排水等待 `drain_wait` 落点 + checkpoint 广播接收点，best-effort）、`core/signals.py`（run 控制文件信号写入）；`bin/fenixd_supervisor.py` 不改（SIGKILL 等待已联动 `shutdown_drain_seconds + 120s`）。
- **验证联动**：`core/pm_engine/verification/judge_gate.py` 或 pipeline（小缺陷判定与子集重验触发）、`core/code_fix.py`（轻量车道承接评估）。
- **spec-review**：评审结果产出与消费两侧的字段扩展（`spec_review` 相关模块）。
- **配置模板**：`.fenix/config.template.yaml`（max_concurrent 推荐值、排水窗口新配置项）。
- **文档**：运行时配置的人工调整步骤（`.fenix/config.yaml` 的 max_concurrent、模型链等）写入 `docs/help/` 或对应运维文档。
- **测试**：预检判定、排水窗口配置、fastlane 阈值、rejection schema 兼容性用例。
- **风险面**：并发 5 放大网关长尾与回归锁排队（full-suite.lock 等待 600s 上限已有 skip 语义兜底）；预检误拦（交集判据保守，允许显式跳过预检的配置逃生门）；fastlane 阈值漏放大缺陷（超阈值回落整轮路径保底）。
