# 裁决 env 豁免与 admin 升级链握手

<!-- knowledge: capability=verdict-env-exemption-handshake rev=3
     sources=spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake,spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit -->

judge 裁决产出 env 归类（豁免清单非空）时的强制握手：豁免不得自我批准，必须经「补救探针 → inconclusive 重验 → 穷尽后 admin 确认 → 豁免生效」才能落 verified；豁免的生效判据、失效语义与 verified 洗白门禁同源。

## 规则

- 拦截点与判据：judge 裁决采纳尾段（进度核对/报告闸门/洗白门禁/transition 之前）在落 verified 终态前，按级二判据检查裁决产物的断言级分类（`assertion_triage`，场景缺该字段时回退场景级 `classification`）：全部失败断言均归类 env（不存在 product-bug / test-defect 条目）时，MUST NOT 直接落 verified——该轮转 inconclusive 处理（回 implemented、保留失败现场、排队重验新 attempt）。
- 边界：含 product-bug / test-defect 条目时握手不命中，走既有 bug-found 流程（env 部分照常留豁免记录）；flaky 归类维持既有豁免放行、不纳入环境性；全绿机械快道（0 失败 0 警告）无豁免对象，不受影响。
- 与级一防线的分工：级一（judge 前全批 blocked-env 短路）命中即 return、judge 不跑；级二在采纳尾段判定且先于 verified 洗白门禁——级二命中即转重验，该轮不再到达洗白门禁，同一轮两道裁决后防线不叠加动作。
- 计数单源：级一级二共享 `_inconclusive_attempts`（同一重验上限与 B7 升级阈值），单轮内两级互斥，无双计数漂移。
- 重验前补救：inconclusive 重验派发前 MUST 先执行环境补救动作（至少含 dist 新鲜度探针与自动重建，见 [serving-dist-freshness-probe](../verify-pipeline/serving-dist-freshness-probe.md)），使重验具备真实翻绿条件；补救失败记入重验轮错误现场供裁决与 admin 参考，MUST NOT 静默吞掉。框架只做自身权限内的补救（重建产物），事件源诊断等环境修复属 admin 职权。
- 穷尽后 admin 确认：重验达 `verify_engine.inconclusive_max_attempts`（缺省 3）仍存在 env 类失败时，走既有 B7 升级通道写 SIGNAL 唤起 Administrator 做环境处置，自动重验暂停，SPEC 停留在 implemented + error 现场（不新增状态机状态）。
- 豁免生效唯一源：spec 级 STATE 字段 `_env_exemptions`（JSON 字符串清单，条目含场景 id、归一化失败签名、场景定义 hash、granted_at 时效锚点与 disposition_id 回链；字段名与结构常量在 state_machine 单源定义，升级握手/洗白门禁/grant 写入共用）。豁免由人工裁决动作 grant_env_exemption 写入；AdminStore DISPOSITION 仍随 grant 落记录但仅为审计镜像。DISPOSITION 或 STATE 写失败不执行重置（fail-closed——「重置了却没豁免」会让重验后的全 env 轮被门禁重新拦截）。
- 双门同源消费：升级握手与 verified 洗白门禁对同一 STATE 豁免清单、经同一纯函数做「场景 id + 签名」匹配——命中有效豁免的 env 项不计入 whitewash_violations；无豁免上下文零行为变化；0-pass 不可白化与「STATE 读失败=无豁免」的 fail-closed 语义保持。
- 豁免匹配口径：签名归一化为数字→N、去引号、折叠空白；签名体取首失败断言 type + 归一化 actual（截断 120 字符），blocked-env 场景（从未执行、无失败断言）签名退化为 `blocked-env`，pass 场景无豁免对象；同场景 id 多条豁免取最近 granted_at。
- 豁免失效双锚：场景定义 hash 变化（grant 时记冻结定义 hash，校验时以冻结场景文件当前定义重算比对；冻结文件缺失/读失败=无变更证据不判失效）或 granted_at 起 72 小时 TTL 过期，任一即失效。豁免清单封顶 64 条，追加时截断保留最近条目。
- 存量通道边界：握手仅在 STATE 无豁免时保留 `latest_resolved_disposition`（signal_type=inconclusive_loop）存量放行查询作回退；STATE 豁免在场但对本轮 env 失败场景未全部命中（场景修订/TTL 过期/签名漂移）时 MUST NOT 回退 disposition 通道——否则「场景变更即失效」被架空，双门矛盾复发。存量 disposition 不做数据回填（无 STATE 豁免即无豁免，重走一次裁决即重建）。
- 冻结计数豁免轮豁免：豁免有效命中的 env 阻塞升级轮不计入 ENV_BLOCK_FREEZE_THRESHOLD（豁免认可不得仍滑向冻结）；TTL 过期或场景定义变更失效后恢复计数，冻结兜底保留（阈值维持 2，见 [blocked-reverify-gate](../verify-pipeline/blocked-reverify-gate.md)）。
- env 归因证据门：env 归因结论的佐证文本含媒体管线词汇（帧/解码/编码/相机/视频/推流/采样/md5 等）时，MUST 同时给出送帧侧与解码侧两段证据引用，缺任一侧该结论降级为 inconclusive（不触发 env 豁免/升级语义）；不含媒体词汇的普通 env 归因（端口失联、依赖缺失等）不受此门约束；本门只对 env 结论收紧，不做任何放行放宽。
- 信号预算：级二触发的重验不判 bug-found、不计 repeated_failures（重验通道不烧困境信号预算，与级一同源）。

## 关键行为

混合形态（如 19 passed + 2 failed + 1 blocked_env）在级一漏出后由级二兜住：judge 将失败全部归类 env 并倾向 verified → 采纳尾段拦截 → 转 inconclusive 重验（先补救探针重建 dist）→ 穷尽后 B7 SIGNAL 唤起 admin → 人工 grant_env_exemption 写 STATE 豁免并重置重验 → 重验轮双门同源命中豁免 → 合法 verified（报告带 env_exemptions 回链）。STATE 豁免在场但场景已被修订或 TTL 过期时，握手与洗白门禁同判拒绝、转升级停车。

## 溯源

- 2026-10-03 fix-verdict-env-exemption-admin-handshake（spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake） — 新建本页：豁免清单非空阻断直接 verified（级二判据挂 judge 采纳尾段、与级一共享 inconclusive 计数）、重验前补救探针、重验穷尽后 B7 升级与 AdminStore DISPOSITION 放行记录锚定的豁免生效握手。
- 2026-10-15 evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit（spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit） — 豁免生效锚自 AdminStore disposition 切换为 spec 级 STATE 字段（升级握手与洗白门禁双门同源消费、disposition 降审计镜像且不回填），补豁免失效双锚（场景定义 hash + 72h TTL）与 64 条封顶、豁免有效轮不计冻结阈值、env 归因证据门（媒体词汇须送帧/解码双段证据，缺则降级 inconclusive）。
