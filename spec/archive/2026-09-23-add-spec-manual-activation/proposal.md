## Why

现有 SPEC 定时拾取（`start_after`）只能表达「某个绝对时间点之后拾取」，缺少「永不到期、等人发话才拾取」这一档：用户常常只想先把 SPEC 登记、冻结住调度，待自己择机再放行——用过去时间会立即派发，用未来时间又得反复续期，冻结（blocked）则会污染状态语义并触发告警巡检。同时，列表页对「等依赖」的 SPEC 毫无提示：`depends_on` 只在详情页可见，用户在列表上看到 ready 却迟迟不派发时无从判断是卡在依赖还是真卡住。

## What Changes

- 新增 `start_after` 哨兵值 `manual`：为 **BREAKING**（字段语义扩展，非格式破坏）——`start_after` 由「ISO8601 UTC 时间戳或 null」扩展为「ISO8601 UTC 时间戳 / 哨兵 `manual` / null」三态。取值为 `manual` 时表示「永不到期，须人工激活后方可被调度器拾取」。
- 所有既有 `start_after` 门控（派发候选筛选、`_on_spec_ready`、recovery 恢复、admin 巡检、假就绪巡检）自动覆盖哨兵值——未激活的 SPEC 一律静默跳过，不写 error、不翻状态（沿用既有防自触发语义）。
- 新增「激活」动作：把 `start_after` 由 `manual` 置为 null 并即时唤醒派发（复用既有 `scheduling_kick_request.json` 文件信号）。
- 各立项入口新增「手工激活」选项：`/fenix-new` 对话确认、自进化「同意立项」弹窗、Dashboard「修改状态」弹窗（对 ready SPEC 双向：设为待激活 / 激活）。
- 新增 CLI 子命令 `bin/fenix_cli.py activate <spec>` 与 `/fenix-ready` skill 放行时的手工激活选项。
- Dashboard 列表：`start_after == manual` 且 ready 的 SPEC 状态列额外显示「待激活」tag；ready 且 `depends_on` 有值时显示「前置依赖」tag，hover 展示依赖 SPEC 名称。
- Dashboard 列表接口（`/api/specs`）摘要新增 `depends_on` 字段（并纳入摘要索引指纹），使列表页可渲染依赖 tag。该字段须经**规范化**后透出（`depends_on` 未登记在解析器 null 归一化键表，`- depends_on: null` 解析回来是**字面量字符串 `"null"`**，本仓库实测 227/244 条），否则前端裸真值判定会让所有无依赖 ready SPEC 误标「前置依赖」。

## Capabilities

### New Capabilities
- `spec-manual-activation`: SPEC 手工激活——`start_after` 哨兵值 `manual` 的字段契约（写入路径：fenix-new / evo 同意立项 / dashboard 修改状态 / CLI / fenix-ready）、调度器门控全路径覆盖、激活动作（置 null + 唤醒信号）、各入口的「手工激活」选项

### Modified Capabilities
- `scheduled-spec-pickup`: 扩展 `start_after` 字段的取值域与格式校验——除 ISO8601 UTC 与 null 外接受哨兵 `manual`；明确该值「永不阻塞到期检测」（`check_scheduling_deadlines` 不误判为到期）；dashboard 修改入口对 `manual` 的读侧展示与写侧校验
- `dashboard-spec-table`: 列表状态列新增两个标记 tag——「待激活」（ready + `start_after == manual`）与「前置依赖」（ready + `depends_on` 有值，hover 显示依赖名列表）；列表摘要 `SpecSummary` 新增 `depends_on` 字段

## Impact

- **状态机**：`core/state_machine.py` — `status:` 无变化，新增哨兵常量与 `start_after_pending` 对 `manual` 的判定；`serialize`/`parse` 白名单已登记 `start_after`，无需新增字段
- **调度器**：`core/pm_engine/engine.py`（`check_scheduling_deadlines` 到期检测须跳过 `manual`、`_on_spec_ready` 门控）、`core/pm_engine/dispatch/queue.py`（候选筛选两处）、`core/event_bus.py`（recovery）、`core/admin_monitor.py`（巡检）——均为既有门控，哨兵值经 `start_after_pending` 单点生效，无需逐处改动
- **Dashboard 后端**：`core/dashboard/data/admin_actions.py`（`set_spec_start_after` 接受 `manual`；新增激活函数）、`core/dashboard/data/summary.py`（`spec_summary` 增 `depends_on` 并纳入 `_ENTRY_SIG_KEYS`）、`core/dashboard/routes/spec_routes.py` / `evolution_routes.py`（新增激活 API / 接受 `manual`）
- **Dashboard 前端**：`core/dashboard/static/src/pages/projects/list.tsx`（两个 tag 组件、菜单项）、`core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`（激活/设为待激活按钮）、`core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx`（同意立项的手工激活选项）、`core/dashboard/static/src/services/dashboard.ts`（类型与 API 封装）
- **CLI**：`bin/fenix_cli.py`（新增 `activate` 子命令）；`bin/fenix_status.py` / `bin/fenix_process.py`（`get_spec_start_after` 改原样返回哨兵后，两处 CLI 展示点须把 `manual` 渲染为「待激活」而非 `_local_ts` 伪时间戳与「⏰ 定时」）
- **Skill**：`skills/fenix-new/SKILL.md`（§1.6 执行时机增「手工激活」档）
- **状态文件**：`start_after` 取值域扩展，存量 null/ISO 值零迁移
- **非目标**：不改 `depends_on` 的调度语义（仅展示）、不改 `promote_mode` 语义（手工激活只拦「ready→派发」，不拦「drafted→ready 晋升」）
