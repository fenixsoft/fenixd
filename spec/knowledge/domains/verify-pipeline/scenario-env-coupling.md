# 验证场景环境耦合红线

<!-- knowledge: capability=scenario-env-coupling rev=1
     sources=spec/knowledge/_inbox/done/consolidate-alerts-e2e-prod-interference-arbiter-blacklist.md -->

验证场景运行在共享真实环境之上：账本是跨项目共享的生产账本，验证实例依赖按浮动范围安装。本页约束场景作与修复同环境的耦合方式，拦截「结构合法但在真实数据在场时必败、或误伤生产状态」的场景形态。

## 规则

- **共享账本改状态操作必须三重作用域**：跨项目共享账本按全局 created 倒序聚合（如运维告警列表 severity 不置顶），「点击第一行」的语义是「点击当前最新一条记录」，外部真实记录插入即错位——位置点击的改状态操作会把生产记录误标记为已处置。此类场景必须同时满足：①选择器作用域到夹具种子行（`[provfix-seed]` 判别前缀 + `:has-text`，位置无关）；②`expect_network` 锁定夹具 id 路径（端点子串含种子记录 id，如 `/api/alerts/<seed-id>/handled`）；③破坏性批量端点（mark_all_handled 类全量清空确认）禁止机器人执行——只开确认弹窗断言确认键机械形态（danger 样式、可交互、trial 探测），取消路径与零副作用语义由独立场景覆盖。种子供给契约见 admin-ops 域 [alert-fixture-seeds](../admin-ops/alert-fixture-seeds.md)。
- **全局聚合量只断言形态**：徽标等全局聚合量（运维页告警徽标 = 全项目未处理带 choices 告警数）的绝对值由全部项目实时账本决定，外部告警在场时「恰为 N」「N→N-1」类断言必翻；引擎 text_match 断言仅 exact/contains/regex 三模式，无相对量表达。聚合量断言只允许形态断言（regex `\d+`），递减/变化语义由作用域性质断言承载——种子 id 网络守卫证明「这次交互确实处置了这条种子」，种子行分组收敛证明「这条种子已离开未处理集」。
- **组件库按钮文本断言用容器作用域**：Playwright `:text/:text-matches` 作为 CSS 伪类只匹配「包含该文本的最小元素」；antd Button 文本恒包在 `<span>` 内（双字按钮 autoInsertSpace 必包 span），`button:` 前缀要求 button 自身是最小元素，对 antd 组件按钮结构性 0 命中。断言组件按钮文本用容器作用域 + 裸 `:text-matches`（如 `.ant-modal-confirm :text-matches("取\\s*消")`）或走祖先语义的 `:has-text`；禁止 `<tag>:text-matches(...)` 直接锚组件按钮。正则 `\s` 一律写双反斜杠（JSON 文本内 `\\\\`），对空格/无空格两种渲染形态同时稳定。双汉字文本选择器的静态情报面见 [scenario-static-defect-scan](scenario-static-defect-scan.md)。
- **断言只依赖语义形态**：前端 lockfile（`core/dashboard/static/pnpm-lock.yaml`）不入 git，验证实例按 semver 范围浮动安装，同一天内不同轮实例的组件库渲染行为即可分叉（antd 双字按钮 autoInsertSpace 的 span 包裹形态轮间漂移）。场景断言只允许依赖语义形态——元素可见、文本正则容空白、结构容器；禁止依赖字节形态——精确空格、span 层级、类名 hash（`css-*` 生成类）。

## 代码锚点

- 主实现：`core/verify_engine/assertions.py`（text_match 断言 exact/contains/regex 三模式单源——相对量断言的词表边界）
- 单源符号：`core/verify_engine/scenarios.py`（expect_network 字段形态与 URL 模式匹配单点——种子 id 网络守卫挂载面）
- 消费方：`core/dashboard/routes/alert_routes.py`（告警聚合读侧——全局 created 倒序与徽标数据源）；`core/verify_engine/scenario_static_check.py`（双汉字文本选择器静态情报）；`core/admin_store.py`（种子写入共享账本的真实通道）
- 守卫测试：`tests/test_scenario_static_check.py`、`tests/test_verify_engine_network_assertion.py`

## 溯源

- 2026-11-12 consolidate-alerts-e2e-prod-interference-arbiter-blacklist（spec/knowledge/_inbox/done/consolidate-alerts-e2e-prod-interference-arbiter-blacklist.md） — 新建本页：折叠 consolidate-alerts-to-ops-page 冻结复盘的四条场景红线（共享账本改状态三重作用域、全局聚合量只断言形态、组件按钮文本容器作用域断言、断言只依赖语义形态含依赖浮动现状）；同条目的 arbiter 处置黑名单反转为待立项机制方向，不入规则段
