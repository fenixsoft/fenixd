## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: tests/test_impl_ocr_parallel_lane.py
  kind: new
- path: tests/test_impl_code_review_gate.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 配置读取器与缺省值

- [ ] 1.1 `core/config.py` 新增单点读取器 `get_impl_code_review_mode`：读 `verify.impl_code_review_mode`，仅接受 `gate`/`advisory` 白名单（非法值回退缺省 `gate` 并 DEBUG 留痕），与既有 `get_impl_code_review_*` 读取器同款语义
- [ ] 1.1b `core/config.py` 新增单点读取器 `get_impl_code_review_lane_timeout_sec`：读 `verify.impl_code_review_lane_timeout_sec`，缺省 2400，与 `get_impl_code_review_timeout_sec` 同款（正整数 int、bool 不算、脏值 fail-open 回退缺省）；语义为**车道级硬超时**，与既有单请求超时键 `impl_code_review_timeout_sec`（缺省 600，被 `_write_run_ocr_config` 消费）按键分离
- [ ] 1.2 `get_impl_code_review_concurrency` 缺省值 2→4（显式配置行为不变），docstring 更新取值来源说明
- [ ] 1.3 `.fenix/config.template.yaml` 的 `verify` 段补 `impl_code_review_mode` 示例键与注释（gate/advisory 语义一句话说明）、补 `impl_code_review_lane_timeout_sec: 2400` 示例键；并**同步把既有示例值 `impl_code_review_concurrency: 2` 改为 4**（模板示例值对模板派生配置即显式配置、会压过读取器新缺省，不同步则 1.2 的缺省调整对模板用户失效且模板与读取器缺省漂移）

## 2. 实现者内联审查段摘除

- [ ] 2.1 `core/agent_runner/prompt_builder.py`：`_impl_code_review_section` 退役（implementer/fast-track 不再注入内联收尾审查段；保留函数壳并置 docstring 说明替代车道，或整体删除并清理调用点，二选一以调用点零残留为准）
- [ ] 2.2 `core/agent_runner/result_gate.py`：实现者产物硬门摘除 `_check_impl_code_review_artifact` 调用（结果文件 `code_review`/`dispositions` 段不再校验）；`_check_impl_code_review_artifact` 函数本体保留供 join 侧复用
- [ ] 2.3 改造 `tests/test_impl_code_review_gate.py`：摘除内联门断言、新增「实现者不带 code_review 段可正常过门」用例，定向测试全绿

## 3. run_impl_ocr 异步车道

- [ ] 3.1 `core/agent_runner/maintenance_runs.py` 新增 `run_impl_ocr`（对齐 `run_code_review`/`run_regression` 形态）：在实现分支 head（detached 检出或复用 tester 检出）跑 `bin/ocr_review.py review --from <base> --to <head>`，`--concurrency`/`--effort` 取配置注入；不占 spec 预算、不走 `_execute_agent`；token 记账对齐 `run_code_review` 形态（`_accumulate_code_review_tokens`/`_append_token_run` 同款），避免车道 token 逃逸仪表盘成本观测
- [ ] 3.2 `core/agent_runner/runner.py`：车道 provider 注入复用 `_write_run_ocr_config` 同源机制（框架侧直调）；产物写 `.fenix/verify-progress/<spec>/code-review.json`（含 `(branch, merge_base, head_commit)` 指纹与 `status: completed|unavailable` 白名单），拷回单向 worktree→主树沿用既有通道
- [ ] 3.3 硬超时与降级：车道受 `impl_code_review_lane_timeout_sec`（新键，缺省 2400s，见 1.1b；与既有单请求超时键 `impl_code_review_timeout_sec` 分离）约束；超时/非零退出/provider 不可达/非 git 仓库 → 写 `unavailable` + 非空 `reason` 结束，MUST NOT 抛未捕获异常
- [ ] 3.4 增量游标：`.fenix/verify-progress/<spec>/ocr-cursor.json` 记 `last_reviewed_commit`；重跑优先 `--from <cursor>` 增量审查，cursor 缺失/非分支祖先回退全量；审查成功后推进游标
- [ ] 3.5 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 登记 `impl-ocr-` 前缀（时间线归属不为泛型）

## 4. 派发接线与 testing 出口 join

- [ ] 4.1 `core/pm_engine/dispatch/queue.py`：merge-back 成功且 tester 派发的同一时点启动 `run_impl_ocr`（`verify.impl_code_review` 开启时；fast-track 车道在其 merge-back 成功时点 `core/pm_engine/dispatch/fast_track.py:512` `merge_back_from_branch` 同点启动）；车道完成事件唤醒 join 评估（复用既有文件信号/唤醒机制，无惰性停等）
- [ ] 4.2 testing 出口 join 判据：`testing → verified` 门禁路径增加 ocr 产物校验（存在 + status 白名单 + 指纹新鲜）；**产物缺失或车道未运行（如 daemon 重启恢复经 `testing → implemented` 重派 verifier 路径再派 tester、无 merge-back 事件）→ 幂等触发 `run_impl_ocr`（在跑单飞去重），MUST NOT 无限停等而车道从未启动**；tester 先完成而 ocr 未完成 → spec 停留 testing、不重派 tester（tester_run 单飞不变）
- [ ] 4.3 指纹 stale fail-closed：`completed` 但指纹与当前 `(branch, merge_base, head_commit)` 不符 → 不采信不放行，触发车道按当前指纹重跑
- [ ] 4.4 gate 档打回：非 rejected findings 且 `_ocr_fix_rounds` < 1 → `testing → bug_found`（reason 注明 ocr findings）→ implementing 重派修复轮，spec entry 计数器 `_ocr_fix_rounds` 递增持久化
- [ ] 4.5 轮次上限与转台账：`_ocr_fix_rounds` ≥ 1 时仍出现的 findings 全部写 code-review 台账 `items.jsonl`（status=open——台账条目词表仅 open/resolved/ignored、无 deferred；spec_name 归属本 spec、finding 附处置 reason），join 放行
- [ ] 4.6 advisory 档：`get_impl_code_review_mode` 为 advisory 时，非 rejected findings 写台账后 join 直接放行，永不打回；unavailable 产物在两档下均放行 + WARNING 审计留痕

## 5. 修复轮 findings 注入段

- [ ] 5.1 `core/agent_runner/prompt_builder.py` 新增修复轮动态段：实现者被 ocr findings 打回时注入 findings 清单、disposition 处置契约（fixed/rejected/deferred + 非空 reason）、修码后重验要求（定向测试 + 全量回归走有界入口前台直跑）；产物路径为 worktree 相对路径（沿用 fix-impl-code-review-writepath 教训，禁止主树绝对路径字样）

## 6. Dashboard 配置界面

- [ ] 6.1 `core/dashboard/data/config_admin.py`：`verify.impl_code_review_mode` 纳入受管键读写回显（白名单校验 gate/advisory）
- [ ] 6.2 `core/dashboard/static/src/services/dashboard.ts` + `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`：「验证」面板新增模式选择（gate/advisory），与并发/超时既有控件同布局风格
- [ ] 6.3 `npm run build` 通过，产物落 `core/dashboard/static/dist/`

## 7. 车道与 join 测试

- [ ] 7.1 新增 `tests/test_impl_ocr_parallel_lane.py`：覆盖车道启动时点、指纹 stale fail-closed、超时降级 unavailable、join 三分支（双绿放行/gate 打回/上限转台账）、advisory 永不打回、增量游标回退全量、tester 停等不重派、产物缺失/车道未运行幂等触发启动（含重启恢复重派路径）、fast-track 同点启动与出口 join
- [ ] 7.2 全量回归走有界入口自证：与基线对比零引入失败
