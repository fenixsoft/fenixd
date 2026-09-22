# Proposal: add-impl-ocr-parallel-lane

## Why

`verify.impl_code_review` 开启后，实现者的收尾代码质量审查（ocr / open-code-review，经 `bin/ocr_review.py` 包装器）被绑死在实现者 run 的**进程生命周期内**：提示词段（`prompt_builder._impl_code_review_section`）要求实现者在写 `.fenix-run-result.json` 之前前台跑完 ocr 并落盘 `code-review.json`，产物硬门（`result_gate._check_impl_code_review_artifact`）在同 run 结束点机械校验。而 ocr 单轮耗时 20~40 分钟、`claude -p` 工具调用硬上限约 600s——实测（`impl-add-code-review-auto-fix-1790046405`，2026-09-22）：

- 前台 ocr 570s 被工具超时截杀，报告未落盘；
- 后台重跑（timeout 2400s 兜底）期间实现者以 sleep 150/240/270s 轮询空烧轮次，run 又撞网关黑洞无事件 42 分钟，daemon 判死重派——**ocr 中间产物全部作废，新 run 从头再跑**；
- 同一 run 内全量回归（后台有界入口）仅 275s 完成且零引入失败。

即：**验证分钟级、ocr 半小时级，且等待本身制造了新的失败面**（轮询烧轮次、网关 stall 放大为 run 挂死、重派作废重跑）。根因是架构性的：把一个长时外部异步任务塞进了一个只能同步等待、一次性结束的 agent run 容器里。

## What Changes

- **实现者收工不再等 ocr**：删除/替换实现者与 fast-track 提示词中的内联收尾审查段（`_impl_code_review_section`）——实现者完成全部任务并提交后直接收工，`code_review` 段与 `dispositions` 不再是其收工义务；产物硬门同步摘除该项校验。
- **新增框架侧 ocr 异步车道**：`maintenance_runs` 形态的 `run_impl_ocr`（对齐 `run_code_review`/`run_regression`），在 merge-back 成功、tester 派发时点启动，与测试验证**并行**执行；ocr 审查范围绑定 `(branch, merge_base, head_commit)` 指纹；run 级 provider 注入复用 `_write_run_ocr_config` 同源机制（框架驱动，不占 agent turn、不占 spec 预算）。
- **join 裁决于 testing 出口**：`testing → verified` 门槛增加 ocr 车道完成判据（报告存在 + 指纹新鲜）——tester 先完成时 spec 停在 testing 等 ocr 完成事件唤醒推进；ocr 车道独立硬超时（`impl_code_review_timeout_sec`，缺省 2400s），**超时/失败降级 `unavailable` 不阻塞 spec**（与现行「环境不可用降级」语义一致）。
- **gate 双档模式**：新增 `verify.impl_code_review_mode: gate | advisory`（缺省 `gate`）。gate 档：join 时存在需修正 findings → 走既有 `testing → bug_found → implementing` 打回通道，实现者修复轮以 ocr findings 为修复义务，修复后重验（定向测试+全量回归）；**ocr 修复轮上限 1 次**（计数器持久化于 spec entry），第二轮仍出的 findings 一律转台账（deferred）。advisory 档：findings 全部入 code-review 台账（`items.jsonl`，喂给 code-fix 自动修复车道），join 永不打回。
- **findings 评估义务机械化**：join 裁决只做机械分类（有无非 rejected findings）；「真实问题 vs 误报」的驳回裁量归修复轮实现者（提示词注入 findings 清单与处置契约，复用现行 disposition 语义）。
- **配置读取器与设置页**：`ConfigLoader.get_impl_code_review_mode` 单点读取器；设置页「验证」面板新增模式选择（gate/advisory）——新配置键必须带 Dashboard 界面。
- **顺手项**：`impl_code_review_concurrency` 缺省 2→4；恢复续做轮 ocr 增量审查——已审过 commit 范围记入 worktree 侧游标文件，重跑只审游标之后的增量 commit。

## Capabilities

### New Capabilities

- `impl-ocr-parallel-lane`：框架侧 ocr 异步车道——触发时点（merge-back 后 tester 派发）、run 级 provider 注入、`(branch, base, head)` 指纹绑定、独立硬超时、失败降级、进度产物落盘（`.fenix/verify-progress/<spec>/code-review.json`，框架侧写入）。
- `impl-ocr-join-gate`：testing 出口 join 裁决——完成判据（指纹新鲜 + status 白名单）、gate 档打回（bug_found 通道 + 修复轮上限 1 次）、advisory 档入台账、tester 单飞与 ocr 完成唤醒。

### Modified Capabilities

- `impl-code-review-gate`（归档能力，现行内联形态）：实现者内联收尾审查义务与同 run 产物硬门**移除**，由上述两能力替代；fast-track 车道同 treatment（内联段摘除，run 收尾由框架侧车道接管，join 于其验证出口）。

## Impact

- **配置契约**：`.fenix/config.yaml` 新增可选 `verify.impl_code_review_mode`（缺省 gate，旧配置零迁移）；`impl_code_review_concurrency` 缺省值 2→4（显式配置不受影响）。
- **代码**：
  - `core/agent_runner/prompt_builder.py`（内联段摘除 + 修复轮 findings 段注入）
  - `core/agent_runner/result_gate.py`(实现者门摘除 ocr 校验；join 判据辅助函数)
  - `core/agent_runner/maintenance_runs.py`（`run_impl_ocr` 执行函数）
  - `core/agent_runner/runner.py`（ocr 车道启动钩子、provider 注入复用、产物拷回）
  - `core/pm_engine/dispatch/queue.py`（tester 派发时点启动车道、testing 出口 join、唤醒接线）
  - `core/config.py`（mode 读取器 + concurrency 缺省调整）
  - `core/dashboard/data/config_admin.py` + `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx` + `core/dashboard/static/src/services/dashboard.ts`（mode 键受管读写回显与设置页 UI）
- **风险**：gate 档修复轮引入「修码后重验」成本（定向测试+全量回归，实测回归 275s，可接受）；join 停等期间 spec 占用 testing 态（tester_run 单飞不受影响）；ocr 上游行为变化只影响车道内部，指纹机制保证 stale 报告不被采信。
