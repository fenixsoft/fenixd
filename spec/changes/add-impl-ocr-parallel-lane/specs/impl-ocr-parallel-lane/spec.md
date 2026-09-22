# impl-ocr-parallel-lane

## ADDED Requirements

### Requirement: 框架侧 ocr 车道在 merge-back 成功后与测试验证并行启动

merge-back 成功且 tester 派发时，框架 MUST 在同一时点启动一次 `run_impl_ocr` 维护 run（对齐 `run_code_review`/`run_regression` 形态），在实现分支（或其等价检出）上执行收尾代码质量审查。实现者 run 与 fast-track run 的收工义务 MUST NOT 再包含内联 ocr 审查。

#### Scenario: tester 派发时 ocr 车道并行启动
- **WHEN** 某 spec 的实现分支 merge-back 成功、tester run 被派发，且 `verify.impl_code_review` 开启
- **THEN** 框架同点启动 `run_impl_ocr`（run_id 前缀 `impl-ocr-`，run 级 provider 注入与该 spec 实现轮同源），tester 与 ocr 车道并行执行，互不等待

#### Scenario: 实现者收工不再等待 ocr
- **WHEN** 实现者完成全部 tasks.md 任务并提交、准备写 `.fenix-run-result.json`
- **THEN** 其提示词与产物硬门均不含 ocr 审查义务，实现者 run 在任务完成后立即收工；`code_review` 段/`dispositions` 数组不再是硬门校验项

#### Scenario: ocr 车道不占 spec 预算与 agent 轮次
- **WHEN** `run_impl_ocr` 执行
- **THEN** 该车道为框架驱动的维护 run（`_execute_agent` 之外），不递增 spec 维度 impl_run 预算、不占用实现者 agent 的对话轮次

### Requirement: ocr 车道绑定 (branch, base, head_commit) 指纹且独立硬超时

ocr 审查 MUST 绑定 `(branch, merge_base, head_commit)` 三元组指纹并写入产物；车道 MUST 受 `verify.impl_code_review_lane_timeout_sec`（新键，缺省 2400s；与既有 LLM 单请求超时键 `impl_code_review_timeout_sec` 缺省 600s 按键分离）硬超时约束。超时、非零退出、provider 不可达、非 git 仓库等失败形态 MUST 降级为 `status: "unavailable"` + 非空 `reason`，MUST NOT 阻塞 spec 推进。

#### Scenario: 指纹不匹配的报告按 stale 处理
- **WHEN** join 判据读到一份 code-review 产物，其指纹与当前 spec 的 `(branch, merge_base, head_commit)` 不一致（如修复轮后 head 前移）
- **THEN** 该产物判为 stale，不参与 join 裁决；车道按需重跑或按降级语义处理，绝不见 stale 报告即放行

#### Scenario: ocr 车道超时不拖死 spec
- **WHEN** `run_impl_ocr` 超过硬超时仍无产物，或以非零退出/环境不可用失败
- **THEN** 车道写 `status: "unavailable"` + 非空 `reason` 后结束；join 判据视 unavailable 为放行（记 WARNING 审计），spec 正常推进

### Requirement: 恢复续做轮 ocr 增量审查

已审过的 commit 范围 MUST 记入游标（如 worktree 侧 `.fenix/verify-progress/<spec>/ocr-cursor.json` 记 `last_reviewed_commit`）；同分支续跑 `run_impl_ocr` 时 MUST 以 `--from <last_reviewed_commit> --to HEAD` 只审增量。游标缺失或 base 失效时 MUST 回退全量审查。

#### Scenario: 恢复续做轮只审增量
- **WHEN** 实现 run 挂死重派后重跑 ocr 车道，游标记录 `last_reviewed_commit=C1`，分支 head 已到 C2（C1 为 C2 祖先）
- **THEN** 本次审查范围为 `C1..C2` 增量 diff，产物 findings 合并游标之前的既有结论；C1 不在分支历史时回退全量
