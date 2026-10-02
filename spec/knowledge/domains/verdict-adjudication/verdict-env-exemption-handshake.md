# 裁决 env 豁免与 admin 升级链握手

<!-- knowledge: capability=verdict-env-exemption-handshake rev=2
     sources=spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake -->

judge 裁决产出 env 归类（豁免清单非空）时的强制握手：豁免不得自我批准，必须经「补救探针 → inconclusive 重验 → 穷尽后 admin 确认」才能生效落 verified。

## 规则

- 拦截点与判据：judge 裁决采纳尾段（进度核对/报告闸门/洗白门禁/transition 之前）在落 verified 终态前，按级二判据检查裁决产物的断言级分类（`assertion_triage`，场景缺该字段时回退场景级 `classification`）：全部失败断言均归类 env（不存在 product-bug / test-defect 条目）时，MUST NOT 直接落 verified——该轮转 inconclusive 处理（回 implemented、保留失败现场、排队重验新 attempt）。
- 边界：含 product-bug / test-defect 条目时握手不命中，走既有 bug-found 流程（env 部分照常留豁免记录）；flaky 归类维持既有豁免放行、不纳入环境性；全绿机械快道（0 失败 0 警告）无豁免对象，不受影响。
- 与级一防线的分工：级一（judge 前全批 blocked-env 短路）命中即 return、judge 不跑；级二在采纳尾段判定且先于既有场景级 env 洗白门禁（`_env_whitewash_gate` 覆盖场景级标注形态，行为不变）——级二命中即转重验，该轮不再到达洗白门禁，同一轮两道裁决后防线不叠加动作。
- 计数单源：级一级二共享 `_inconclusive_attempts`（同一重验上限与 B7 升级阈值），单轮内两级互斥，无双计数漂移。
- 重验前补救：inconclusive 重验派发前 MUST 先执行环境补救动作（至少含 dist 新鲜度探针与自动重建，见 [serving-dist-freshness-probe](../verify-pipeline/serving-dist-freshness-probe.md)），使重验具备真实翻绿条件；补救失败记入重验轮错误现场供裁决与 admin 参考，MUST NOT 静默吞掉。框架只做自身权限内的补救（重建产物），事件源诊断等环境修复属 admin 职权。
- 穷尽后 admin 确认：重验达 `verify_engine.inconclusive_max_attempts`（缺省 3）仍存在 env 类失败时，走既有 B7 升级通道写 SIGNAL 唤起 Administrator 做环境处置，自动重验暂停，SPEC 停留在 implemented + error 现场（不新增状态机状态）。
- 豁免生效唯一锚：AdminStore 中该 SPEC 的已处置放行记录（kind=DISPOSITION 且 result ∈ resolved / partially-resolved，经 `latest_resolved_disposition` 按 spec + signal_type 查询；dashboard/CLI 人工放行动作落库后同一锚点可查）。守卫检查点放在级二命中分支内：查得放行记录 → 本轮直接按既有豁免清单落 verified（报告保留豁免清单与 admin 处置回链）；查不得 → 转重验。admin 介入前框架 MUST NOT 以豁免清单为依据自行产出最终 verified。
- 信号预算：级二触发的重验不判 bug-found、不计 repeated_failures（重验通道不烧困境信号预算，与级一同源）。

## 关键行为

混合形态（如 19 passed + 2 failed + 1 blocked_env）在级一漏出后由级二兜住：judge 将 2 个失败全部归类 env 并倾向 verified → 采纳尾段拦截 → 回 implemented 排队重验 → 重验前探针重建 dist → 全绿则自然 verified。连续达升级阈值（缺省 4）轮次均为「失败全部 env」→ SIGNAL 唤起 admin、暂停自动重验 → admin 处置确认不可解并人工放行 → 按豁免清单落 verified。

## 溯源

- 2026-10-03 2026-10-03-fix-verdict-env-exemption-admin-handshake（spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake） — 新建本页：豁免清单非空阻断直接 verified（级二判据挂 judge 采纳尾段、与级一共享 inconclusive 计数）、重验前补救探针、重验穷尽后 B7 升级与 AdminStore DISPOSITION 放行记录锚定的豁免生效握手。
