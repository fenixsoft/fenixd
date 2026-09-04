# Design: add-task-progress-sync

## Context

实现 Agent 按 prompt 要求应在完成任务后勾选 tasks.md，但实际服从率低（多个 pushed SPEC 进度 0%）。现有补偿是读侧的：`core/dashboard/data.py` 的 `_parse_run_task_done` 从 impl run 产物解析 TaskCreate/TaskUpdate 完成集合并实时叠加到进度显示，但只在 run 文件存活期间有效，且不落盘、不做完成度校验。run 文件被清理后（当前 .fenix/runs/ 已只剩最近 SPEC 的产物），历史 SPEC 进度永久失真。

关键现状：
- 解析逻辑已存在且经过验证（TaskUpdate taskId 为 1 基创建序，需与 TaskCreate subject 内嵌 id 对齐）
- PM Engine 在 `agent_runner` 回调中已知 run 终态（success/error），是回写的天然挂载点
- verified→done 转换集中在 `_on_spec_verified`（pm_engine.py:132），auto approve 链路单一

## Goals / Non-Goals

**Goals**
- run 成功后由 daemon 把已确认完成的任务确定性写回主树 tasks.md 并 commit
- verified→done 前校验「声明 success vs 任务全完成」一致性，不一致时阻断推送并暴露缺口
- 修复型 SPEC（fix-*）同样生效

**Non-Goals**
- 不改变 implementer prompt 中「第 6 步自行勾选」的要求（保留双通道，agent 勾了更好）
- 不改动 Dashboard 读侧实时叠加（implementing 期间的实时视图仍需要它）
- 不追溯修复历史 pushed SPEC 的 tasks.md（成本高、价值低）

## Decisions

1. **回写挂载在 PM Engine 的 run 终态处理处，而非 agent_runner 内部**
   agent_runner 只负责跑子进程；PM Engine 拥有状态机与 git 操作上下文（merge-back 也在此层）。回写是「项目级状态维护」，归属一致。
   备选：在 agent_runner 收尾处回写——但它无 STATE.md 访问权，且 worktree 清理时序耦合更深，放弃。

2. **复用 `_parse_run_task_done` 的解析语义，提升为共享函数**
   将解析核心移到独立可导入位置（如 data.py 公有化或抽到 core/ 下新模块），pm_engine 与 dashboard 共用，避免两套正则漂移。注意该函数有 memo 缓存，回写调用前须确认缓存键含 mtime/size（已满足）。

3. **只增不减的并集语义**
   回写仅把 `- [ ]` → `- [x]`（id 精确匹配），绝不撤销任何勾选。agent 自行勾选的任务即使 run 记录缺失也保留。这保证回写在任何乱序下都是安全的。

4. **门禁放在 verified→done 转换前（_on_spec_verified），而非 approve_push 内**
   在状态转换点拦截比在每个推送入口重复校验更收敛；阻断时保持 verified 状态 + error 字段记录缺口清单，人工 `/fenix-approve` 时可见。approve_push 本身不再二次校验（避免双重拦截逻辑）。
   备选：在 approve_push 校验——但 legacy verifier 与三阶段流程都会触发 verified→done，入口分散，放弃。

5. **sync commit 用固定 message 前缀并与 agent 提交区分**
   `[fenix] <spec>: sync task progress from run record`。merge-back 与后续 diff 审阅时可一眼识别 daemon 自动提交。若工作树不干净（如 merge-back 冲突恢复期），跳过本次回写并在下个调度周期重试，不阻塞主流程。

## Risks / Trade-offs

- [run 文件先于回写被清理] → 门禁侧对「无 run 记录可查」的情况放行（无法证伪即放行），回写侧静默跳过；不因缺证据而卡死流程。
- [TaskUpdate 与 TaskCreate 对齐失败（subject 无 id）] → 沿用现有 flat 下标回退语义；回写仅在 id 可精确匹配时执行，flat 回退只用于显示不做落盘，避免错勾。
- [回写 commit 与 merge-back 时序竞争] → 回写仅在 run 终态处理点执行一次，且幂等；冲突时下轮重试，最坏情况是进度短暂滞后。
- [门禁误拦（任务清单里本就不打算做的条目）] → error 字段明确列出未完成任务 id，人工 /fenix-approve 可裁决推进；这是有意为之的暴露而非故障。

## Migration Plan

纯增量变更，无数据迁移。上线后新完成的 SPEC 自动获得回写与门禁；存量 pushed SPEC 维持现状（进度失真已知、可接受）。

## Open Questions

- 无。
