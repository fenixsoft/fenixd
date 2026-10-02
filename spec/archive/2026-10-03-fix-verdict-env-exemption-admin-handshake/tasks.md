## Deliverables

```yaml
- path: core/worktree_manager/dist_conflicts.py
  kind: modify
- path: core/pm_engine/verification/serving.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: tests/test_verify_env_handshake.py
  kind: new
```

## 1. dist 构建入口复用化（merge-back 单点扩散的前置）

- [x] 1.1 `core/worktree_manager/dist_conflicts.py`：把 `_run_dist_build` 的构建执行体（从 `.fenix/verify.yaml` prepare 段读构建契约 + 子进程执行 + 失败尾部日志截取）提取为模块级函数（如 `run_dist_build(project_root, static_root, logger) -> bool`），`_rebuild_dist_after_merge` 改为调用该函数，行为逐字节不变（含失败时 `dist rebuild fallback build failed` 日志口径与 stderr[:200] 截取）；既有 dist_conflicts 相关测试全量通过

## 2. serving 层 dist 新鲜度探针

- [x] 2.1 `core/pm_engine/verification/serving.py`：新增探针函数——比对 dashboard static src 树最新 mtime 与 served dist 入口产物（`dist/index.html`）mtime，src 较新即判滞后；served dist 不存在或被测实例为 worktree 自建形态（prepare 已在本 worktree 构建）时探针直通；探针在验证场景开跑前执行一次，场景间不重复
- [x] 2.2 `core/pm_engine/verification/serving.py`：探针判滞后时调用任务 1.1 的 `run_dist_build` 自动重建，成功后开跑；重建失败 MUST NOT 静默开跑——错误现场（构建失败尾部日志）写入本轮 run 错误字段与 logger.error，并按环境性失联语义返回（该轮按 blocked-env/inconclusive 路径处置，供豁免握手与 admin 升级链消费）；dist 新鲜时零动作直通（无重建、无额外副作用）

## 3. 裁决豁免握手（级二判据 + 尾段拦截）

- [x] 3.1 `core/pm_engine/verification/escalation.py`：新增级二判定辅助——读 judge 裁决产物断言级分类（`assertion_triage`，场景缺该字段时回退场景级 classification）：全部非 pass/passed 场景（含 blocked_env 形态，天然视为环境性）的失败断言中无 product-bug / test-defect 条目且全部失败断言归类均为 env 即命中；含 product-bug / test-defect 条目不命中（走既有 bug-found，env 部分照常留豁免记录）；flaky 归类维持既有豁免放行不转重验；判定输入为裁决产物字段，不重算原始 summary，MUST NOT 用「豁免清单条数 == failed + blocked_env」等式（豁免清单为断言级行，与场景数不对齐）
- [x] 3.2 `core/pm_engine/verification/pipeline.py`：judge 采纳尾段（进度核对/报告闸门/洗白门禁/transition 之前）新增拦截——级二命中时 MUST NOT 落 verified，转为与 `_handle_env_blocked_inconclusive` 同源的 inconclusive 处理（回 implemented、`tester_run` 清空、`_inconclusive_attempts` 加一、attempts≥2 并行度降档复用、重验排队）；阶段 2.6 命中即 return 的既有短路保证单轮内两级互斥；拦截点先于既有 `_env_whitewash_gate` 洗白门禁，级二命中即 return 转 inconclusive（该轮不再到达洗白门禁），级二不命中时洗白门禁行为不变；无豁免（豁免清单空）时零改动直通，全绿机械快道不受影响
- [x] 3.3 `core/pm_engine/verification/escalation.py` + `pipeline.py`：级二重验穷尽复用既有 B7 通道（attempts 达 `verify_engine.inconclusive_escalate_attempts` 缺省 4 → `_write_inconclusive_loop_signal` 写 SIGNAL、暂停自动重验）；豁免最终落地加守卫，守卫检查点在级二命中分支内——以 AdminStore 处置记录为唯一锚（kind=DISPOSITION，`latest_resolved_disposition` 按 spec 查询；dashboard/CLI 人工放行动作落库后同一锚点可查）：查得放行记录 → 本轮直接按既有豁免清单落 verified 并在报告保留处置回链；查不得 → 转 inconclusive，豁免清单不得作为 verified 依据，SPEC 保持 implemented + error 现场等待人工

## 4. 测试与回归

- [x] 4.1 新建 `tests/test_verify_env_handshake.py`：级二判据用例——混合形态（原始 failed>0 且断言级 triage 全部 env、场景级 classification 未标 env）命中转 inconclusive、含 product-bug / test-defect 断言不命中走 bug-found、flaky 断言混合形态维持既有豁免放行不转重验、全批 blocked-env 级一先命中短路（judge 不被调用）、豁免清单为空 verified 直通
- [x] 4.2 同文件补升级与守卫用例：`_inconclusive_attempts` 达升级阈值写 SIGNAL 且暂停自动重验、无 admin 放行记录时豁免不得落 verified、放行记录存在后豁免生效且报告含处置回链
- [x] 4.3 同文件补探针用例（tmp_path 伪造 src/dist mtime）：dist 新鲜直通零重建、滞后重建成功后开跑、重建失败错误现场留痕且不静默开跑、worktree 自建形态直通；`tests/` 既有验证链相关测试（inconclusive、environment-sanity、fast-track 快道）全量回归通过
