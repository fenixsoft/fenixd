# add-pipeline-throughput-governance 设计

## Context

调度与合并侧的四个结构性耗时点（全历史 277 完成spec实测）：

- **实现排队 893h（37.1%）**：`max_concurrent` 代码缺省 2（`dispatch/queue.py` `_get_config("agents.max_concurrent", 2)`）、运行时配置 3；单巨型 spec 垄断时其余 spec 长尾等待（09-16 实证 7 个 spec 各等 15-18h）。
- **merge-back 长尾**：`done→pushed` P50 14s 但均值 41m——138 次 git 冲突告警，「尝试 merge→冲突→autostash→回滚→重试」循环；既有治理（evo-merge-back-wip-overlap-gate 系列、`core/wip_checkpoint.py`）已覆盖部分场景，但均为**事后**补救。
- **重启杀在飞**：drain 上限 1800s ≫ supervisor 60s SIGKILL 宽限（三 run 悬空 12h 事故根因）；09-22 04:17 一次重启杀掉 3 个在飞 40-70m 的 impl run。
- **bug-found 修复环**：120 次 bug-found，`bug-found→implemented` P90 12.7h——单场景小缺陷也走整轮 fix SPEC 派生 + 全场景重验。

关联现状：`agents/code-fix.md` 轻量修复 agent 已存在；`bin/fenixd_supervisor.py` 入库、restart_request 文件信号机制已有；spec-review 结果 JSON 已有结构化字段先例。

## Goals / Non-Goals

**Goals:**

- 并发缺省与模板推荐值统一为 5，吞吐上限提升且可回退。
- merge 前拦截可预判的 WIP 重叠冲突，消灭「merge 失败→回滚→重试」循环的无效轮次。
- 重启排水窗口与 supervisor 宽限不再结构性错配。
- 小缺陷修复走轻量通道 + 子集重验，修复环时长数量级下降。
- spec-review 打回可按 format/substantive 分类统计。

**Non-Goals:**

- 不改调度优先级/抢占语义（priority 队列行为保持）。
- 不做 implementer run 内长命令的后台化改造（用户明确排除）。
- 不改 fix SPEC 派生逻辑本身（fastlane 是其旁路，非替代）。
- 不改 supervisor 的进程管理模型（只协调排水窗口与广播信号）。

## Decisions

1. **并发上调 = 缺省值与模板双改 + 逃生门**：`queue.py` 缺省 2→5、`config.template.yaml` 推荐值 3→5（含注释说明资源前提：worktree 磁盘 ~N×仓库大小、网关并发压力、full-suite.lock 串行化回归）。运行时 `.fenix/config.yaml` 实际调整为人工步骤（写入 `docs/help/14-pipeline-throughput-ops.md` 并在 README 索引登记 + `.fenix/todo.md` 登记）。full-suite.lock 主机锁（等待上限 600s、超时 skip 语义已有）是多 spec 回归互斥的既有保障，本 SPEC 不改其行为。备选「只改运行时配置不改代码」被否：缺省 2 对无配置部署的下游项目不生效。

2. **merge 预检 = 前置交集判定 + 升级而非尝试**：merge-back 发起前计算「主树 WIP 脏文件集（`git status --porcelain` 解析）∩ 分支触碰文件集（`merge-base..branch` diff 文件集）」，交集非空 → 不发起 merge，直接发人工升级告警（choices 通道，附交集文件清单），spec 保持 done 可重试状态（人工清理 WIP 后重试或显式豁免）。**先读 `evo-merge-back-wip-overlap-gate` 归档 spec 与 `core/wip_checkpoint.py` 现状**：既有 overlap-gate 已覆盖的判定直接复用/前置调用，不重复实现；本 SPEC 的增量是「把判定从 merge 失败后前移到 merge 发起前」+「统一走人工升级出口」。配置逃生门：`merge_precheck_bypass: true` 时跳过预检（紧急推送用）。

3. **排水窗口协调 = 新配置项 + 默认对齐 supervisor 宽限**：新增 `agents.run_drain_max_seconds`（缺省 60s，与 supervisor SIGKILL 宽限一致；`bin/fenixd_supervisor.py` 侧宽限同步读取同一配置或保持 60s 不动）。restart 流程：收到 restart_request → 停新派发 → 向在飞 run 广播 checkpoint 信号（写 run 控制文件，implementer prompt 已有响应语义的则以既有语义收尾落盘进度声明，无则 best-effort 忽略）→ 等待排水至多 `run_drain_max_seconds` → 超窗强杀走既有路径。备选「延长 supervisor 宽限到 1800s 匹配现 drain」被否：重启等待半小时的现状本身就是要治的病（用户已有「重启要等半小时」的抱怨记录）。

4. **fastlane 判定阈值固化三条件**：①单场景失败（该验证轮失败场景数 = 1）；②judge 归因的修复影响面 ≤3 文件；③无 judge 争议（judge verdict 无 dispute/adjudication 标记）。三条件全满足 → 生成 code-fix 轻量任务（`agents/code-fix.md` 车道，主树或既有分支直接修复），修复后构造子集场景集（失败场景 ∪ depends_on 前置链）重验，通过即完成本轮；任一条件不满足 → 既有 bug-found→fix SPEC 路径原样。子集重验独立可用（不依赖 verdict 缓存 SPEC 合入：直接以子集场景集作为本轮场景集执行，绕过缓存逻辑）。fastlane 修复轮次计入该 spec 既有验证轮预算，连续 2 次 fastlane 失败 → 强制回落整轮路径（防轻量通道打转）。

5. **rejection_class 枚举 = format / substantive / unknown（缺省）**：spec-review 结果产出侧在打回（reviewing→drafted）时必写该字段；判定标准写入评审 prompt 注入段（格式类=草稿结构/契约段/键名等可机械修复问题，实质类=方案/覆盖/正确性问题）；消费侧与统计口径把缺字段按 unknown 兼容（存量结果文件零迁移）。前端不做（本期统计走读侧数据层字段）。

## Risks / Trade-offs

- **并发 5 放大网关长尾与资源压力** → 配置可即时回退（运行时配置人工调回 3）；网关侧已有瞬断熔断与 failover 治理兜底。
- **预检误拦（假阳性交集）** → 交集判据本身保守（真实会冲突的文件集才拦）；bypass 逃生门 + 升级告警附交集清单，人工可秒判。
- **排水窗口过短杀掉本可收尾的 run** → 缺省 60s 与 supervisor 现状一致（不劣化）；checkpoint 广播提高窗口内收尾率；配置可调大。
- **fastlane 修小缺陷引入新缺陷** → 子集重验 + 连续 2 次失败强制回落整轮；修复 diff 仍过既有 code-review 门（不豁免）。
- **与 add-verify-lane-throughput 并行实现触碰同文件**（judge_gate.py 等）→ 不同 hunk 区域，可自动合并；冲突按手术式提交处方处理。
