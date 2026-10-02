# ocr 异步审查车道（run_impl_ocr）

<!-- knowledge: capability=impl-ocr-parallel-lane rev=1
     sources=spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

框架侧维护 run 形态的收尾代码审查车道：merge-back 成功、tester 派发时点启动，与测试验证并行执行，把半小时级的 ocr 审查从实现者 run 的同步等待容器中解耦出来。

## 规则

- 触发时点：实现分支 merge-back 成功且 tester run 被派发时（`verify.impl_code_review` 开启），框架在同一时点启动一次 `run_impl_ocr`（对齐 `run_code_review` / `run_regression` 维护 run 形态），在实现分支（或其等价检出）上执行收尾代码质量审查；run_id 前缀 `impl-ocr-`，run 级 provider 注入与该 spec 实现轮同源。
- tester 与 ocr 车道并行执行、互不等待；实现者完成全部 tasks.md 任务并提交后立即收工，收工义务不含内联 ocr 审查。
- 车道是框架驱动的维护 run（`_execute_agent` 之外）：不递增 spec 维度 impl_run 预算，不占用实现者 agent 的对话轮次。
- 指纹绑定：审查绑定 `(branch, merge_base, head_commit)` 三元组指纹并写入产物；指纹不匹配的报告（如修复轮后 head 前移）判 stale，不参与 join 裁决，绝不见 stale 报告即放行；车道按需重跑或按降级语义处理。
- 独立硬超时：车道受 `verify.impl_code_review_lane_timeout_sec`（缺省 2400s）约束；该键与既有 LLM 单请求超时键 `impl_code_review_timeout_sec`（缺省 600s，被 run 级 provider 注入消费）按键分离，两种粒度的超时不共用一键。
- 失败降级：超时、非零退出、provider 不可达、非 git 仓库等失败形态一律降级为 `status: "unavailable"` + 非空 `reason` 后结束，不阻塞 spec 推进；join 判据视 unavailable 为放行（记 WARNING 审计）。
- 进度产物落盘 `.fenix/verify-progress/<spec>/code-review.json`（框架侧写入）；运行中心跳与时间轴可见性见 [ocr-lane-liveness-heartbeat](ocr-lane-liveness-heartbeat.md) / [timeline-ocr-lane-visibility](timeline-ocr-lane-visibility.md)。
- 恢复续做轮增量审查：已审过的 commit 范围记入游标（worktree 侧 `.fenix/verify-progress/<spec>/ocr-cursor.json` 的 `last_reviewed_commit`）；同分支续跑 `run_impl_ocr` 时以 `--from <last_reviewed_commit> --to HEAD` 只审增量，产物 findings 合并游标之前的既有结论；游标缺失或 base 失效（last_reviewed_commit 不在分支历史）时回退全量审查。

## 溯源

- 2026-09-26 add-impl-ocr-parallel-lane（spec/archive/2026-09-26-add-impl-ocr-parallel-lane） — 新建框架侧 ocr 异步车道：tester 派发时点并行启动、`(branch, base, head)` 指纹绑定与 stale 判定、独立硬超时键（2400s，与单请求超时键分离）与失败降级、维护 run 形态（不占 spec 预算与 agent 轮次）、恢复续做轮增量审查游标。
