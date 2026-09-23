## Context

`start_after` 定时拾取（archive `2026-09-12-add-spec-scheduling-controls`）已把「时间点门控」贯通全链：单一事实源 = STATE.md entry 字段，共享谓词 `start_after_pending(entry, now)`（`core/state_machine.py:97`）覆盖全部派发入口（`engine._on_spec_ready:551`、`dispatch/queue.py:233/317`、`event_bus._recover_ready:264`、`admin_monitor.py:471`、`engine.py:2534`），到期检测挂 daemon 主循环 60s 计时段（`engine.check_scheduling_deadlines:595`，`fenixd.py:570`）。

**关键既有行为（决定本次实现方式）：**
- `start_after_pending` 语义为 fail-open：字段缺失/null/`parse_utc` 解析失败一律返回 `False`（不阻塞）。**直接塞哨兵值 `manual` 会被解析失败吞掉 → 该 SPEC 被当作无限制立即派发**——这是本次最核心的坑，哨兵必须在谓词里显式优先判定。
- `check_scheduling_deadlines:663` 已对 `parse_utc(sa) is None` 的 spec `continue`（无到期检测需求），哨兵天然不会被误判为「到期」。
- 清空 `start_after` 的即时唤醒已存在：写 `.fenix/scheduling_kick_request.json`（`admin_actions._write_scheduling_kick_signal:350`）→ daemon 主循环 1s 粒度 `_check_scheduling_kick_requests`（`fenixd.py:1047`）消费并唤起 `_on_spec_ready`。激活动作可直接复用该信号，无需新增机制。
- 列表摘要 `spec_summary`（`core/dashboard/data/summary.py:251`）不含 `depends_on`，`_ENTRY_SIG_KEYS`（`summary.py:403`）不含 `depends_on` → 列表页拿不到依赖信息；`depends_on` 仅详情端点暴露（`summary.py:652`）。
- 前端状态元数据单点 `STATUS_META`/`statusMeta`（`static/src/services/dashboard.ts:745`），状态列 render 在 `list.tsx:750`，时间 tag `ScheduledPickupTag`（`list.tsx:234`，`dayjs("manual")` 非法 → 返回 null，不会误渲染倒计时）。

## Goals / Non-Goals

**Goals:**
- `start_after` 新增哨兵值 `manual`：永不到期，须人工激活后方可被调度器拾取
- 全派发入口对哨兵值一律静默跳过（复用既有 `start_after_pending` 单点，不逐处改动）
- 激活动作 = `start_after → null` + 复用 `scheduling_kick_request.json` 即时唤醒
- 各立项/放行入口提供「手工激活」选项：`/fenix-new`、evo 同意立项、Dashboard 修改状态、CLI `activate`、`/fenix-ready`
- Dashboard 列表新增「待激活」（ready + manual）与「前置依赖」（ready + 有依赖）两个 tag

**Non-Goals:**
- 不改 `depends_on` 的调度语义（本次仅「展示」依赖，不放宽/收紧 `_dependencies_satisfied`）
- 不拦「drafted→ready 晋升」：手工激活只拦「ready→派发」，晋升仍按 `promote_mode` 走
- 不新增 STATE 字段：复用 `start_after` 单字段（`manual` 与定时值互斥）
- 不做「待激活」的过期/告警机制（人工激活本就是有意等待，对齐冻结/start_after 的「按计划」语义）

## Decisions

### D1: 哨兵值常量与谓词优先级（`core/state_machine.py`）
新增模块级常量 `START_AFTER_MANUAL = "manual"`。`start_after_pending` 在解析前显式判等：

```python
value = (entry or {}).get(START_AFTER_FIELD)
if value is None:
    return False
if isinstance(value, str) and value.strip().lower() == START_AFTER_MANUAL:
    return True          # 哨兵：永不到期，等价「永远 pending」
when = parse_utc(value)
...
```

**为何在谓词内判等而非复用 parse_utc**：fail-open 语义要求「非法值不阻塞」，而哨兵是**合法值**且语义相反（永远阻塞）。两者必须在同一点分派，否则散落各消费点时必有一处按 fail-open 误放行（该缺口正是「静默放行未激活 SPEC」的高危形态）。判定大小写不敏感 + `strip`，容错人工手改 STATE.md。

`parse_utc` **不**改：它只认时间戳，哨兵不是时间。`get_spec_start_after`（读侧，供 dashboard）单独识别哨兵并原样返回 `"manual"`。

### D2: 全派发入口零改动覆盖
哨兵经 `start_after_pending` 单点生效，`engine._on_spec_ready` / `dispatch/queue.py` / `event_bus._recover_ready` / `admin_monitor` / 假就绪巡检**全部无需改动**（它们只调谓词）。任务清单仍逐点核对，防新派发入口绕过（沿用 add-spec-scheduling-controls 的验证范式）。

### D3: 到期检测不误判哨兵（`engine.check_scheduling_deadlines`）
现逻辑 `if sa is None or parse_utc(sa) is None: continue` 已跳过哨兵（`parse_utc("manual") is None`）。**MUST NOT** 顺手改成 `sa != null` 之类——保留该行为，并在注释中显式标注「哨兵经 parse_utc 判 null 天然跳过到期检测，勿改」。回归测试覆盖「manual 的 SPEC 反复过 60s tick 不被唤起」。

### D4: 激活动作 = 置 null + 唤醒信号（`core/dashboard/data/admin_actions.py`）
新增 `activate_spec(project_root, spec) -> dict`：
- spec 不在 STATE.md → `{found: False}`
- 当前 `start_after` 非 `manual` → `{ok: False, reason: "该 SPEC 并非待激活态"}`（幂等拒绝，不误清定时值）
- 命中 → `sm.update_spec(spec, {"start_after": None})` + `_write_scheduling_kick_signal(proot, spec)`（信号 action 复用 `clear-start-after`，语义等价）
- 返回 `{ok: True, found: True, start_after: None}`

**设为待激活** 复用既有 `set_spec_start_after`：扩展其校验——值 `manual`（大小写不敏感）→ 写入哨兵字符串；否则仍走 `parse_utc` 校验。**终态拒绝**保持（与定时拾取同判据）。

### D5: Dashboard API（`core/dashboard/routes/spec_routes.py`）
- `POST /api/spec-activate?project=&spec=`：body 无参；`activated`/`not-pending`/404 语义对齐 freeze-config 家族（`found` 假 → 404；非待激活 → 200 `{ok: false, reason}`）
- `POST /api/spec-start-after` 扩展：body `value` 接受 `"manual"` → 设为待激活；`null` → 清除（原语义）；ISO → 定时（原语义）
- `POST /api/evolution/accept` 扩展：body 新增可选布尔 `manual_activation`；为真时把哨兵经 `start_after="manual"` 传给 `accept_item`（`core/evolution.py:1238` 原样落入 entry，无需改 accept_item）

### D6: CLI `bin/fenix_cli.py activate <spec>`
新增子命令（与 `promote`/`reflow` 同构：`--project` 解析、`_resolve_project_root`），调 `admin_actions.activate_spec`；成功打印并 exit 0，非待激活/未找到打印原因 exit 1。同步更新模块 docstring 的用法清单。

### D7: `/fenix-new` skill 执行时机三档化（`skills/fenix-new/SKILL.md`）
§1.6 由二选一改三选一：立即执行（不写字段）/ 定时调度（写 ISO）/ **手工激活（写 `"manual"`）**。§3.1.2 增补哨兵换算约定（无需时区换算，直接写字符串）。§4 注册示例补 `'start_after': 'manual'`。

### D8: `/fenix-ready` skill 放行时可选手工激活
放行入口处（用户确认步骤）增一问：「放行后立即调度，还是设为待激活？」。**注意**：`~/.claude/skills/fenix-ready` 是**仓库外**的独立目录（非仓库内 `skills/`，也非软链），无法作为本仓库交付物——本仓库只交付 `skills/fenix-new/SKILL.md` 与文档说明，`fenix-ready` 的改动列入「人工步骤」文档小节，由人工在主树同步（与 `.fenix/` 运行时文件同类的不可交付形态）。

### D9: 前端列表两个 tag（`static/src/pages/projects/list.tsx`）
新增两个纯展示组件，挂在状态列 `Space`（与 `ScheduledPickupTag` 并列）：
- `ManualActivationTag`：`record.start_after === 'manual'` 时渲染橙色「待激活」tag + Tooltip（「已设为手工激活，需人工激活后才会被拾取」）。**不加状态门槛**（manual 与 ready 绑定，但渲染只看字段，避免 drafted 态漏标；若后续语义变化不误伤）
- `DependencyTag`：`record.status === 'ready'` 且 `record.depends_on` 规范化后非空时渲染「前置依赖」tag + Tooltip（依赖名列表，逗号分隔原样展示，与 `_dependencies_satisfied` 的解析口径一致）。判据依赖 D12 的后端规范化——前端**不得**只做 `!!record.depends_on` 真值判定（字面量 `"null"` 为真值，会全线误标）

**为何依赖 tag 仅 ready**：按用户明确要求（`ready` 时才提示「为什么就绪却不派发」）；其它状态的依赖信息属详情页职责。

`SpecSummary` 类型（`services/dashboard.ts:183`）新增 `depends_on?: string | null`。

### D10: 「修改状态」弹窗双向（`SpecStatusModal.tsx`）
非终态区块新增「调度」小节：
- `status === 'ready'` 且 `start_after === 'manual'` → 显示「激活（立即调度）」按钮
- `status === 'ready'` 且非同 manual → 显示「设为待激活」按钮（含确认文案）
- 走 `activateSpec` / `setSpecStartAfter(..., 'manual')` 两个 service 封装

### D11: evo 同意立项弹窗三档（`SuggestedImprovementsPanel.tsx`）
`AcceptScheduleFields` 的 Radio.Group 由两档（立即/指定时间）扩为三档，新增 `value="manual"`「手工激活」。`commit` 逻辑：`manual` → `holder.startAfter = 'manual'`。后端 `/api/evolution/accept` 已有 `start_after` 透传（D5 仅放大校验以接受哨兵）。

### D12: 后端摘要新增 `depends_on`（`core/dashboard/data/summary.py`）
`spec_summary` 返回值增 `"depends_on"`，取值**必须经规范化**（不能直接 `entry.get("depends_on")`）：

```python
def _normalize_depends_on(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "null":   # 与调度器 _dependencies_satisfied 的 deps == "null" 同口径
        return None
    return text
```

**为何必须规范化（实测证伪点）**：`depends_on` **未**登记在 `StateParser._parse_content` 的 null→None 归一化键表里（`core/state_machine.py:313-337` 仅含 FROZEN_FIELD / START_AFTER_FIELD / FROZEN_UNTIL_FIELD / 若干 run 与 _ 前缀字段），而 `serialize` 对空值恒写 `- depends_on: null`（`core/state_machine.py:389-391`）。本仓库 `.fenix/STATE.md` 实测：244 条 entry 中 **227 条** 的 `depends_on` 解析回**字面量字符串 `"null"`**（`read_all()` 实测分布 `{"'null'": 227, ...}`）。若摘要原样透出，前端 `非空` 判据对 `"null"` 恒为真 → **所有无依赖的 ready SPEC 都会被渲染「前置依赖」tag（tooltip 显示 `null`）**，恰好摧毁本 tag 的存在意义（区分「卡在依赖」与「真卡住」）。这也是既有详情页 `detail.tsx:1505` `{detail?.depends_on || '无依赖'}` 显示成 `null` 的同源坑。

`_ENTRY_SIG_KEYS` 增 `"depends_on"`（否则依赖变化不使索引失效，列表 tag 滞后）。纯读、无副作用。

## Risks / Trade-offs

- **[哨兵被 fail-open 误放行（最核心风险）]** → D1 谓词内显式优先判等 + 专测「manual 的 spec 在各派发入口均不被拾取」；「静默放行未激活 SPEC」是本次最高危失败形态，任务清单单列覆盖全部入口
- **[`get_spec_start_after` 把 manual 折叠成 None 致前端丢标记]** → D12/读侧单独识别哨兵原样返回；前端 tag 与「设置拾取时间」弹窗预填均按 `'manual'` 分支处理
- **[`get_spec_start_after` 改为原样返回哨兵后的读侧扩散]** → 该函数是**共享读函数**，除摘要外还有 `bin/fenix_status.py:168/276`、`bin/fenix_process.py:277` 两处 CLI 消费点，它们把返回值一律经 `_local_ts` 当时间渲染（`_local_ts` 对非 ISO 走 except 回退 `str(raw)[:19]`）。不改则待激活 SPEC 在 `fenix-status` 会显示「⏰ 定时」备注与 `start_after manual` 伪时间戳——事实错误。任务 5.3/5.4 逐点覆盖；MUST NOT 靠「折叠回 None」绕过（那会违反 `scheduled-spec-pickup` 的「哨兵原样返回」MUST）
- **[`depends_on` 字面量 `"null"` 污染列表 tag]** → 见 D12：该字段未被解析器 null 归一化，227/244 条存量 entry 解析回字符串 `"null"`（实测），前端裸真值判定会全线误标「前置依赖」。摘要侧必须规范化
- **[「设置拾取时间」弹窗预填哨兵]** → `list.tsx:673` `dayjs('manual')` 为 Invalid Date，`scheduled-spec-pickup` 已 MUST 要求安全降级，任务 7.6 承接
- **[误改 `check_scheduling_deadlines` 致哨兵被判到期]** → D3 保留 `parse_utc is None → continue` 并加注释 + 回归测试
- **[`fenix-ready` 不可交付]** → D8 明确写入「人工步骤」文档，不写进 tasks.md 任务（避免门禁缺口烧预算）
- **[依赖 tag 与索引失效]** → D12 `_ENTRY_SIG_KEYS` 同步加字段；`_ENTRY_SIG_KEYS` 缺项会导致列表依赖 tag 长期陈旧
- **[手改 STATE.md 大小写差异]** → D1 判定 `lower()+strip()` 容错
- **[向后兼容]** → 存量 `null`/ISO 值行为不变；仅新增取值分支，读侧缺省 null 零迁移

## Migration Plan

字段取值域扩展，存量 spec 零迁移。回滚 = 已写 `manual` 的 spec 需人工置 null（或忽略哨兵分支）；无 schema 变更、无数据迁移脚本。

## Open Questions

（无——哨兵存 `start_after`、只拦派发不拦晋升、依赖 tag 仅 ready、dashboard 双向均已与用户对齐）
