# design — fix-verdict-env-exemption-admin-handshake

## Context

验证链的后处理阶段链（`core/pm_engine/verification/pipeline.py` ~1900-1945）依次为：
阶段 2.5 应用不可达 → `_escalate_env_blocked`（blocked + admin）；阶段 2.6
`_handle_env_blocked_inconclusive`（`escalation.py:44`，判据在 ：68——`blocked_env <= 0 or (failed + errors) > 0` 即 return False，只认全批 blocked-env）；阶段 2.7
`_detect_uniform_verify_failure`（pass=0 且同签名 → 呼叫 admin）；阶段 3 全绿机械快道；否则 judge LLM 裁决。

事故形态（add-session-composer 2026-09-25）：原始 summary 19 passed + 2 failed +
1 blocked_env + 1 warning——2.5/2.7 判据不命中（非不可达、非 pass=0），2.6 判据
`failed+errors=2 > 0` 直接 return False；judge 裁决把 2 个 failed 归类 env 产出
verified。三道环境防御全在 judge 之前、以原始口径判定；judge 之后的防线只有
verified 洗白门禁（`_env_whitewash_gate` → `whitewash_violations`，2026-09-04
help-center 防线，escalation.py:177 / verdict_check.py:217），而它只检查**场景级**
`classification == "env"` 且 status 非 pass 的形态——本次事故的裁决豁免走**断言级**
triage（`assertion_triage` 归类 env，报告豁免清单按断言逐条渲染 7 条），场景级
classification 未标 env，从该检查漏出，verified 放行；该形态下 env 归类同样不回流
inconclusive 重验链，admin_monitor 三层检测（repeated_failures /
stuck / blocked_stuck）以失败/error 终态为输入，verified 通过全盲。dist 重建只有
merge-back 单点（`core/worktree_manager/dist_conflicts.py:317`
`_rebuild_dist_after_merge`，失败仅 logger.error 不重试不阻塞），verify prepare 的
build 在 serving worktree 侧跑，刷不到主树 8787 被测实例。

既有可复用机制：inconclusive 重验链（`_inconclusive_attempts` 计数、
`verify_engine.inconclusive_max_attempts=3`、`_verify_parallel_override` 降档）、
B7 升级通道（`_write_inconclusive_loop_signal`，`inconclusive_escalate_attempts=4`
写 SIGNAL 唤起 Administrator）、`core/signals.py:42 request_admin_invoke`、
并行度逐轮减半（attempts≥2）。

## Goals

1. 「失败全部为环境性」的轮次（无论判定时点在 judge 前还是 judge 后）一律走
   inconclusive 重验链，不当健康轮放行。
2. 豁免不得自我批准：verified 落地前豁免清单必须过「重验穷尽 + admin 确认」两道闸。
3. 环境补救动作（dist 重建）前移到验证开跑前，让重验具备真实翻绿条件。

## Non-Goals

- 不改 admin_monitor 三层检测口径（B7 SIGNAL 通道已实证覆盖 inconclusive 形态）。
- 不改 dist gitignore 决策与 merge-back 既有重建逻辑（serving 探针是增量第二触发点）。
- 不改全绿机械快道（0 失败 0 警告无豁免对象，天然不受影响）。
- 不处理裁决 agent 未写 markdown 报告的合成链（独立问题，不在本 SPEC 范围）。

## Decisions

### D1 豁免握手挂 judge 采纳尾段，不新增阶段

拦截点放 judge 采纳尾段（进度核对/报告闸门/洗白门禁/transition 之前），以
「豁免清单非空」为触发条件转 inconclusive。理由：级二判据（裁决后全部环境性）
只能在 judge 之后判定；挂尾段天然覆盖混合形态与全批形态的 judge 后路径，与阶段
2.6（judge 前短路）构成两级防线且互不重复——阶段 2.6 命中即 return，judge 不跑，
尾段不会看到重复轮次。计数复用 `_inconclusive_attempts`（两级共享同一上限与
升级阈值，避免双计数器漂移）。与既有洗白门禁的分工：`_env_whitewash_gate`
（场景级 classification=env 且 status 非 pass → `_escalate_env_blocked`：
blocked + admin + 冻结转人工）保持不变，覆盖场景级标注形态；级二覆盖其漏出的
断言级豁免形态。级二拦截点在洗白门禁之前，级二命中即转 inconclusive（该轮
不再到达洗白门禁），级二不命中时洗白门禁行为逐字节不变——同一轮两道裁决后
防线不叠加动作。

### D2 重验前补救 = dist 探针前置 + 探针结果随 run 留痕

重验派发前执行 serving-dist-freshness-probe（D3）；探针/重建结果写入本轮错误
现场字段，judge 与 admin 均可读。不做更多补救动作（事件源诊断等属 admin 职权，
框架不自作主张改环境）——框架穷尽自己权限内的补救（重建产物），其余升级 admin。

### D3 探针实现：mtime 级时序比对，重建复用 dist_conflicts 构建入口

比对口径取 static src 树最新 mtime vs dist 入口产物（`dist/index.html`）mtime，
不做内容哈希（全树哈希开销大且 vite 产物 hash 文件名会误报）。重建直接调用
`core/worktree_manager/dist_conflicts.py` 的构建执行入口（`_run_dist_build` 所在
类的方法提取复用或模块级函数化），构建命令契约从 `.fenix/verify.yaml` prepare 段
读取（与 merge-back 同源），不在 serving 层硬编码 `npm run build`。探针只对
dashboard static 产物存在且被测实例 serve 主树 dist 的形态生效；worktree serve
形态（prepare 已在本 worktree 构建）探针天然新鲜直通。

### D4 混合形态级二判据实现口径

级二判定读 judge 裁决产物的断言级分类（`assertion_triage`；场景无
assertion_triage 时回退场景级 classification）：全部非 pass/passed 场景（含
blocked_env 形态场景，其天然视为环境性）的失败断言中不存在 product-bug /
test-defect 条目，且全部失败断言归类均为 env——即「失败全部为环境性」方命中；
不重算原始 summary，不用「豁免清单条数 == failed + blocked_env」等式（豁免清单
是断言级行，条数与场景数不对齐，事故形态 7 条断言 ≠ 2 failed + 1 blocked_env）。
含 product-bug（产品缺陷）或 test-defect（测试脚本缺陷）条目时级二不命中、走
既有 bug-found——豁免记录照常保留（部分豁免不阻断缺陷修复流）。flaky 归类
维持既有豁免放行语义不转重验（不扩大本 SPEC 范围）。

### D5 admin 确认的落点复用 B7 + 人工放行语义

级二重验穷尽（attempts 达 `inconclusive_escalate_attempts`）→
`_write_inconclusive_loop_signal` 写 SIGNAL → admin 处置。豁免最终生效以
AdminStore 处置记录为唯一锚（kind=DISPOSITION，经 `latest_resolved_disposition`
按 spec 查询；dashboard/CLI 人工放行动作落库后同一锚点可查）；守卫检查点放在
级二命中分支内：查得该 SPEC 放行记录 → 本轮直接按既有豁免清单落 verified 并在
报告保留处置回链；查不得 → 转 inconclusive 重验。无放行记录前 SPEC 停留在
implemented + error 现场（与既有 B7 「暂停自动重验等待人工处置」语义闭环，
不新增状态机状态）。

## Risks / Trade-offs

- *[误伤健康轮]* 级二把「裁决全部豁免」的轮次打回重验，重验有成本（token/时长）。
  缓解：重验上限 3 次 + 升级阈值 4 次既有封顶；并行度逐轮减半既有降档；豁免零
  开销路径（无豁免）零改动。
- *[震荡]* 探针误判 src mtime（如 git 操作触碰 mtime）导致每轮重建。缓解：重建
  幂等且 vite 增量构建秒级；探针只在 verify run 前执行一次，不在场景间反复。
- *[双计数混淆]* 级一级二共享 `_inconclusive_attempts`，两道防线同轮都可能想加一。
  缓解：阶段 2.6 命中即 return（judge 不跑），单轮内两级互斥，无并发写者。

## Migration Plan

纯增量改动，无数据迁移。上线顺序：先落 D3 探针（独立收益，即使握手未上线也能
消灭 dist 时序类 env 失败），再落 D1/D4 握手，最后 D2 补救联动。daemon 重启生效。

## Open Questions

- 无。判据阈值全部复用既有配置键，不新增调参面。
