# spec-verdict-env-exemption-handshake

## ADDED Requirements

### Requirement: env 豁免非空时阻断直接 verified
judge 裁决采纳尾段 SHALL 在落 verified 终态前按级二判据检查裁决产物的断言级分类（assertion_triage，场景缺该字段时回退场景级 classification）：全部失败断言归类 env（无 product-bug / test-defect 条目）时，MUST NOT 直接落 verified——该轮 SHALL 转入 inconclusive 处理（回 implemented、保留失败现场、排队重验新 attempt），与既有全批 blocked-env 的 inconclusive 语义同源。含 product-bug / test-defect 条目时本要求不命中，走既有 bug-found（env 部分照常留豁免记录）；flaky 归类维持既有豁免放行。全绿机械快道（0 失败 0 警告）无豁免对象，MUST NOT 受本要求影响。

#### Scenario: 裁决豁免触发重验而非放行
- **WHEN** 一轮验证 19 场景通过、2 场景失败，judge 裁决将 2 个失败全部归类 env 并倾向 verified
- **THEN** 采纳尾段拦截该 verified，spec 回 implemented 排队重验，`_inconclusive_attempts` 加一，不产生 bug-found、不计 repeated_failures

#### Scenario: 无豁免的 verified 不受影响
- **WHEN** 一轮验证全部场景通过且裁决无任何 env 豁免归类
- **THEN** 既有 verified 流转不变，不触发重验、不产生额外 run

### Requirement: 重验前执行环境补救探针
inconclusive 重验派发前，框架 SHALL 先执行环境补救动作（至少含 serving-dist-freshness-probe 的 dist 新鲜度探针与自动重建），使重验具备让环境类失败真实翻绿的条件；补救动作的失败 SHALL 记入重验轮的错误现场供裁决参考，MUST NOT 静默吞掉。

#### Scenario: dist 陈旧在重验前被修复
- **WHEN** 首轮 2 个空态文案场景因 served dist 中间态失败被裁决豁免，重验派发前探针检测到 dist 滞后并重建成功
- **THEN** 重验轮 served dist 含最新文案，原 2 场景真实复跑（非豁免放行），全绿则自然 verified

### Requirement: 重验穷尽后豁免须经 admin 确认
inconclusive 重验达到既有上限（`verify_engine.inconclusive_max_attempts`，缺省 3）仍存在 env 类失败时，框架 SHALL 走既有 B7 升级通道：向 admin store 写 SIGNAL 唤起 Administrator 做环境补救处置；AdminStore 中出现该 SPEC 的已处置放行记录（kind=DISPOSITION，经 `latest_resolved_disposition` 可查；dashboard/CLI 人工放行动作落库后同一锚点可查）后，豁免方可生效落 verified。守卫检查点 SHALL 放在级二命中分支内：查得放行记录即本轮直接放行（不再转 inconclusive），查不得则转 inconclusive 重验。admin 介入前框架 MUST NOT 以豁免清单为依据自行产出最终 verified。

#### Scenario: 连续 env 失联唤起 Administrator
- **WHEN** 同一 SPEC 连续达到升级阈值（缺省 4）轮次均为「失败全部归类 env」
- **THEN** admin store 出现该 SPEC 的 SIGNAL 记录，自动重验暂停，等待 admin 环境处置或人工放行

#### Scenario: admin 确认不可解后豁免生效
- **WHEN** admin 处置记录确认事件源在本环境不可达且无补救手段，人工放行
- **THEN** 该 SPEC 以既有豁免清单落 verified，报告保留豁免清单与 admin 处置回链
