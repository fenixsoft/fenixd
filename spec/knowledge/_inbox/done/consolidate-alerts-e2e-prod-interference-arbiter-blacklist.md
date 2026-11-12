# consolidate-alerts-to-ops-page 冻结事故复盘：E2E 生产账本串扰与 Arbiter 黑名单处置哲学

## 背景

2026-11-12，consolidate-alerts-to-ops-page SPEC（fenixd，运维告警聚合页）在验证期烧穿：judge 6 轮触顶 6/5 → 机器冻结（blocked+frozen）→ arbiter 两次派发均 escalate → 人工裁决「改断言、解冻、复盘」。原判「断言期望值写错」被推翻：断言如实失败了，错的是场景与共享生产环境的耦合方式。本条目记录根因事实、由此沉淀的场景红线，以及 arbiter 处置从白名单反转为黑名单的机制方向。

## 结论（当前事实）

### 1. 位置点击是 E2E 红线级缺陷

告警列表按全局 created 倒序聚合（`core/dashboard/routes/alert_routes.py:179-181`），severity 不置顶。任何「点击第一行」的场景步骤，语义都是「点击当前全世界最新的一条告警」——外部真实告警（他项目升级、WIP 滞留、judge_rerun_cap 裁决包）插入即错位。本次机器人据此把 cloud-phone 的真实升级告警 9900aa8588fd 标记为已处理（04:52:48Z），徽标与分组断言随即如实全灭。

**规则**：验证机器人对共享账本做改状态操作时必须三重作用域——①选择器作用域到夹具种子行（`:has-text('[provfix-seed] …')`，位置无关）；②expect_network 锁定夹具 id 路径（如 `/api/alerts/seed-badge-a/handled`，子串匹配即可）；③破坏性批量端点（`POST /api/alerts/clear` 类 mark_all_handled）确认路径禁止机器人执行，E2E 只开弹窗断言确认键机械形态（danger 样式/可交互/trial 探测），取消路径与零副作用由独立场景覆盖。

### 2. 全局聚合量的绝对值在共享账本上不可静态锚定

徽标数=全项目未处理带 choices 告警数。事故取证时外部真实可裁决告警 8 条在场（含两条 judge_rerun_cap 人工裁决包），徽标实显 12 而种子只供给 4——「恰为 4」「4→3」「3→2」类断言在任何外部告警在场时必翻。引擎 text_match 只有 exact/contains/regex 三模式、无相对量断言（`core/verify_engine/assertions.py:757-774`），schema 内无法表达「减一」。

**规则**：徽标等全局聚合量只断言形态（regex `\d+`），递减/变化语义改由作用域性质断言承载（种子 id 网络守卫 + 种子行分组收敛）。绝对值口径验证属框架级能力（账本隔离的验证环境），记 gap 待立项。

### 3. Arbiter 处置应从白名单反转为黑名单

现状是白名单+MUST-escalate：五个救回动作（冻结场景拯救/verdict 考古/计数复位/孤儿 worktree/WIP 分拣）全不命中即必须升级，「这个测试应该改断言」被写明为禁止 arbiter 处置的反例。本次事故证明该哲学在「失败面轮间漂移」场景下失效：真正需要的救回动作（场景鲁棒性修复）不在白名单内，而等 arbiter 拿到信号时 5 轮预算已烧穿、spec 已冻结——处置时机与处置能力双缺位。

**反转方向**：默认 arbiter 可救，仅枚举禁项（黑名单），禁项每条机械可判：

- **B1 破坏性生产副作用**：改动 spec 自身范围之外的生产账本/状态（标记告警、处置裁决包、清空告警存储）。同一条黑名单也应作用于**场景本身**（见结论 1 的三重作用域规则——它本质是把 B1 下沉到场景静态检查层）。
- **B2 人工裁决通道**：消费/关闭任何人工裁决工件（judge_rerun_cap 裁决包、impl_unattainable 确认、/fenix-approve 门）。
- **B3 解冻与预算清零**：unfreeze、计数复位、预算覆盖恒为人工专属；arbiter 可请求不可执行。本次实证：解冻是唯一把 `_judge_rerun_count` 6→0、`_scenario_repair_exhausted_rounds` 1→0 清零的通道。
- **B4 契约变更越权**：改「验证什么」（放宽断言期望、删场景、把期望改成实测值=自证）禁止；改「怎么验证」（选择器作用域、网络守卫收紧、等待时序、夹具隔离）允许。机械判别=语义保持证明：断言集 diff 逐条分类收紧/放松/中性，整体放宽即升级，收紧或持平（本次 `/api/alerts/`→`/api/alerts/seed-badge-a/handled` 是收紧）自动放行。
- **B5 越界写**：state.json、他 spec 分支、主树直接写。

**介入时机**：同签名失败重派 ≥2 即路由 arbiter（黑名单工具箱+独立有界配额，如 2 次救回），救回失败后失败签名必须变化才可再试（防抖）；不要等 5 轮烧完冻结后才首次派发。

### 4. Playwright `:text-matches/:text` 最小元素语义 × antd span 包裹 = 结构性命中不能

解冻后 round 9/10 连败 `button:text-matches("执\s*行")`/`button:text-matches("取\s*消")`，round ≤8 同断言却过——非转义问题（Playwright 选择器解析确实吞一层反斜杠，`\s` 需写成 JSON 级 `\\s`，但那只解释正则形态），真正根因是**最小元素语义**：`:text/:text-matches` 作为 CSS 伪类只匹配「包含该文本的最小元素」，antd Button 文本永远包在 `<button><span>取 消</span></button>` 里（双字按钮 autoInsertSpace 时必包 span），`button:` 前缀要求 button 本身是最小元素 → **对 antd 组件按钮永远 0 命中**。round ≤8 能过纯因当时实例的 antd 渲染 `<button>取消</button>`（无 span 无空格）。实证（活实例 43895）：`button:text-matches(...)`→0、裸 `:text-matches(...)`→命中 span、`has-text` 走祖先语义不受影响。

**规则**：断言组件库按钮的文本可见性，用容器作用域 + 裸 `:text-matches`（如 `.ant-modal-confirm :text-matches("取\\s*消")`）或 `:has-text`；禁止 `<tag>:text-matches(...)` 直接锚组件按钮。`\s` 一律写双反斜杠（JSON 里 `\\\\`），对空格/无空格两种渲染形态同时稳。

### 5. 验证实例依赖浮动：pnpm-lock 不入 git，antd 版本轮间漂移

`core/dashboard/static/pnpm-lock.yaml` 未被 git 跟踪（git ls-files 空），每轮验证实例按 `^6.6.0` 浮动安装——同一天内 round ≤8 与 round 9/10 的实例 antd 渲染行为即已分叉（双字按钮 autoInsertSpace 从不触发变触发，连带结论 5 的命中结构翻转）。E2E 断言的一切「细节形态依赖」在这种环境里都是轮间彩票。

**规则**：verify 实例必须锁定依赖（lockfile 入 git 或实例安装 `--frozen-lockfile`）；场景断言只允许依赖「语义形态」（元素可见/文本正则容空白/结构容器），禁止依赖「字节形态」（精确空格、span 层级、类名 hash 如 `css-wgezi7`）。属框架级修复，与结论 2 的账本隔离 gap 同车立项。

### 6. 修复与解冻事实

5 个场景改写完成（mark-handled 种子作用域+网络守卫收紧、badge-caliber/spec-detail/cancel-noop 徽标改 regex、spec-detail 全交互作用域到裁决种子卡——本 spec 自己的 judge_rerun_cap 裁决包按 created 倒序会排首卡、位置作用域会以 ack_self_heal 程序化误裁决人工裁决包、clear-all-confirm 转安全变体）。引擎 loader 干跑 18/18 过、5 场景逐个 validate OK、静态检查 finding 与改前逐条相同（4 条全为存量告警级提示，零新增）。经 `POST /api/spec-unfreeze?project=fenixd&spec=…`（spec_routes.py:343 → admin_actions.unfreeze_spec → state_machine.unfreeze_spec）官方通道解冻：冻结标记全清、rerun/repair 计数清零、恢复 implementing 态。

## 证据

- 根因链：`.fenix/verify-progress/consolidate-alerts-to-ops-page/report.json` scenarios[ops-mark-handled-badge-decrement]（POST /api/alerts/9900aa8588fd/handled 网络断言过、三断言败）+ 失败截图 `screenshots/ops-mark-handled-badge-decrement_assert_fail_0.png`（首行仍为种子甲未处理形态）。
- 生产副作用与回滚：`/root/cloud-phone/.fenix/admin_alerts.json` id=9900aa8588fd handled_at=04:52:48.822365Z → 已回滚 handled=false（验证窗口全账本 handled_at 逐一核对，唯一附带损伤即此一条；备份 `.history/admin_alerts.cloud-phone.bak-20261112T155333.json`）。
- 爆炸半径盘点（改场景前）：全项目未处理带 choices 告警 12 条=8 真实（cloud-phone e7d1ff485145/ac252a19f5e9/d6b5ba6ad183 裁决包、dsh-plugins 91d365247837、fenix-desktop 18c37b5d7cbe、fenixd 24840fa8aeeb/34ae21ea0362/c0a6984e673a 本 spec 裁决包）+4 种子。
- 校验：`core.verify_engine.scenarios.load_scenarios` 18 场景过、5 改写场景 validate() 空错误列表；`scenario_static_check.scan_scenarios` 改前改后 findings 逐条相同（stale_literal_port×2 存量、double_han_text_selector×2 存量）。
- 解冻前后状态字段：frozen/_frozen_source/_frozen_hold/_judge_cap_frozen 全清；`_judge_rerun_count` '6'→'0'；`_scenario_repair_exhausted_rounds` '1'→'0'；updated=2026-11-12T08:01:24Z。
- 改写后场景文件：`.fenix/verify-progress/consolidate-alerts-to-ops-page/test_scenarios.json`（18 场景、gitignore 内零 WIP 敞口）；改前快照 `.history/scenarios_to_repair.current.json`。
