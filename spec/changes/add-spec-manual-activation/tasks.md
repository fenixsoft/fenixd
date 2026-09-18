# Tasks: add-spec-manual-activation

## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/dashboard/routes/spec_routes.py
  kind: modify
- path: core/dashboard/routes/evolution_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/evolution.py
  kind: modify
- path: bin/fenix_cli.py
  kind: modify
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx
  kind: modify
- path: tests/test_spec_scheduling.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_dashboard_evolution_api.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
- path: tests/test_self_evolution.py
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
```

## 1. 状态机哨兵与门控（核心）

- [ ] 1.1 core/state_machine.py：新增模块级常量 `START_AFTER_MANUAL = "manual"`（置于 `START_AFTER_FIELD` 旁，附注释说明「永不到期哨兵，须人工激活」）；`start_after_pending(entry, now)` 在 `parse_utc` 解析**之前**显式判等哨兵——取值为字符串且 `strip().lower() == START_AFTER_MANUAL` 时直接 `return True`（恒视为未到期），注释点明「哨兵是合法值且语义与 fail-open 相反，必须在此分派，勿下沉到 parse_utc」；`parse_utc` 本身 MUST NOT 改动（哨兵不是时间）
- [ ] 1.2 core/pm_engine/engine.py：`check_scheduling_deadlines` 第 2 段（start_after 到期唤起）在 `if sa is None or parse_utc(sa) is None: continue` 处补注释——显式标注「哨兵 `manual` 经 parse_utc 判 None 天然跳过到期检测，MUST NOT 改为 `sa != null` 之类判据，否则哨兵被判到期误唤起」，MUST NOT 改动该分支行为
- [ ] 1.3 tests/test_spec_scheduling.py：在 `TestSharedTimeTools` 增测试——`start_after_pending({"start_after": "manual"})` 为 True（远期 now 亦真，验证不依赖时间）；`"Manual"` / `"MANUAL"` / `" manual "` 变体均为 True；`"manual-x"`（前缀相似但非哨兵）不因此被误判（回退 parse_utc fail-open → False，即非法值不阻塞）；确认存量 `test_start_after_invalid_parse_is_not_pending` 仍通过

## 2. 激活动作与写侧校验（后端 data 层）

- [ ] 2.1 core/dashboard/data/admin_actions.py：`get_spec_start_after(entry)` 增哨兵识别——`raw` 为字符串且 `strip().lower() == "manual"` 时原样返回 `"manual"`（在 `parse_utc` 之前判定），其余维持既有「非法/null 折叠为 None」语义；导入 `START_AFTER_MANUAL` 常量（从 core.state_machine）
- [ ] 2.2 core/dashboard/data/admin_actions.py：`set_spec_start_after` 扩展 `manual` 分支——值（字符串）`strip().lower() == "manual"` 时 `normalized = "manual"` 直接写入（跳过 `parse_utc` 校验，不写 kick 信号，因为这是「设为等待」而非「恢复调度」）；其余值路径不变；终态拒绝保持
- [ ] 2.3 core/dashboard/data/admin_actions.py：新增 `activate_spec(project_root, spec) -> dict`——spec 不在 STATE.md → `{ok: False, found: False, error}`；status 为 done/pushed → `{ok: False, found: True, terminal: True, error}`；`start_after` 非 `manual` → `{ok: False, found: True, reason: "该 SPEC 并非待激活态（start_after 非 manual）"}`（STATE 零变更）；命中 → `sm.update_spec(spec, {"start_after": None})` + `_write_scheduling_kick_signal(proot, spec)` → `{ok: True, found: True, spec, start_after: None}`；docstring 说明幂等语义与信号复用
- [ ] 2.4 core/dashboard/data/__init__.py：facade 导出 `activate_spec`（加入既有 `from ... import (...)` 列表与 `__all__`，若有）

## 3. 列表摘要暴露 depends_on

- [ ] 3.1 core/dashboard/data/summary.py：`spec_summary` 返回值增 `"depends_on": entry.get("depends_on")`（附注释：列表页「前置依赖」标记数据源）；`_ENTRY_SIG_KEYS` 元组增 `"depends_on"`（否则依赖变化不使索引失效，tag 滞后）；两处顺序无关，保证与 spec_summary 实读字段一一对应

## 4. Dashboard API 与路由

- [ ] 4.1 core/dashboard/routes/spec_routes.py：新增 `_api_spec_activate(query)` handler（POST /api/spec-activate?project=&spec=）——参数解析与错误语义对齐 freeze-config 家族：project/spec 缺失 → 404；调 `dashboard_data.activate_spec`；`found=False` → 404；`terminal=True` → 403；`ok=False`（非待激活）→ 200 + `{ok: false, reason}`；成功 → 200 + `{ok: true, spec, start_after: null}`；异常兜底 500 不崩进程
- [ ] 4.2 core/dashboard/routes/spec_routes.py：`_api_spec_start_after` docstring 与校验说明更新——`value` 现接受 `"manual"`（设为待激活）、“null”（清除）、ISO8601（定时）三态；确认 `set_spec_start_after` 的 manual 分支不被既有 `invalid` 校验误拒（如需，读侧以 `result.get("invalid")` 为准，manual 路径不置 invalid）
- [ ] 4.3 core/dashboard/routes/base.py：新增适配函数 `_post_spec_activate`（调 `s._api_spec_activate(q)`）并在 POST 路由表 `("exact", "/api/spec-activate", _post_spec_activate)` 注册（与 spec-start-after 同区块）
- [ ] 4.4 core/dashboard/routes/evolution_routes.py：`_api_evolution_accept` 的 `raw_start_after` 校验扩展——值 `strip().lower() == "manual"` 时视为合法（跳过 `parse_utc`），`start_after = "manual"` 原样透传给 `accept_item`；docstring 补充「支持哨兵值 manual = 立项即为待激活」

## 5. evo 同意立项与 CLI

- [ ] 5.1 core/evolution.py：`accept_item` 的 start_after 处理确认/补注释——哨兵字符串 `"manual"` 原样落入 entry（`if start_after: entry["start_after"] = start_after` 现有逻辑已满足，若需显式化则补一行注释说明哨兵不经时间换算）；MUST NOT 引入 `parse_utc` 于该写侧（哨兵不是时间）
- [ ] 5.2 bin/fenix_cli.py：新增 `cmd_activate(args)` 与 `activate` 子命令（argparse：`spec` 位置参数 + `--project`），调 `core.dashboard.data.admin_actions.activate_spec`；成功打印「SPEC '<name>' 已激活，立即进入调度」exit 0；非待激活/未找到/终态打印拒绝原因 exit 1；同步更新模块 docstring 顶部「用法」清单与 `subparsers` 注册

## 6. fenix-new skill 执行时机三档化

- [ ] 6.1 skills/fenix-new/SKILL.md：§1.6 执行时机由二选一改三选一——新增「手工激活」档（注册时写 `start_after: "manual"`，永不到期，待人工激活）；建议话术同步；§1.6 正文说明三档各自写入的 STATE 字段值
- [ ] 6.2 skills/fenix-new/SKILL.md：§3.1.2 定时拾取换算约定增补哨兵分支（「手工激活」无需时区/相对时长换算，直接写字符串 `manual`）；§4 注册示例注释补 `'start_after': 'manual'` 形态；规则清单（文末）增一条「手工激活档 MUST 写哨兵值 `manual`，MUST NOT 用未来时间模拟」

## 7. Dashboard 前端

- [ ] 7.1 core/dashboard/static/src/services/dashboard.ts：`SpecSummary` 接口增 `depends_on?: string | null`（对齐详情类型）；新增 `activateSpec(project, spec)` service（POST /api/spec-activate）；`setSpecStartAfter` 类型签名确认接受 `'manual'` 字符串；补 `ActivateResult` 返回类型
- [ ] 7.2 core/dashboard/static/src/pages/projects/list.tsx：新增 `ManualActivationTag` 组件（`record.start_after === 'manual'` 时渲染橙色「待激活」Tag + Tooltip「已设为手工激活，需人工激活后才会被拾取」，否则返回 null）；`ScheduledPickupTag` 保持不动（`dayjs('manual')` 非法已自然返回 null，不误渲染倒计时）
- [ ] 7.3 core/dashboard/static/src/pages/projects/list.tsx：新增 `DependencyTag` 组件（`record.status === 'ready'` 且 `record.depends_on` 非空时渲染「前置依赖」Tag + Tooltip 展示依赖名列表，逗号分隔原样）；在桌面状态列 render（与 `ScheduledPickupTag` 并列）与移动端卡片状态区（`SpecCardList` 同位置）各挂 `ManualActivationTag` 与 `DependencyTag`
- [ ] 7.4 core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx：非终态区块增「调度」小节——`status === 'ready'` 且 `start_after === 'manual'` → 显示「激活（立即调度）」按钮（调 `activateSpec`，确认文案说明将立即派发）；`status === 'ready'` 且非同 manual → 显示「设为待激活」按钮（调 `setSpecStartAfter(..., 'manual')`，确认文案说明将暂停调度待人工激活）；成功后 `onDone()` 刷新
- [ ] 7.5 core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx：`AcceptScheduleFields` 的 Radio.Group 由两档（immediate/scheduled）扩为三档，新增 `value="manual"`「手工激活」选项；`commit` 逻辑——`manual` 时 `holder.startAfter = 'manual'`；`mode` state 类型扩为 `'immediate' | 'scheduled' | 'manual'`；批量接受路径（默认 from config）不受影响

## 8. 文档

- [ ] 8.1 docs/help/06-governance.md：「草稿人工放行」章节同区块新增「SPEC 手工激活（待激活）」小节——说明 `start_after: manual` 哨兵语义（永不到期）、激活入口清单（Dashboard「修改状态」/ CLI `activate` / `/fenix-new` 手工激活档 / evo 同意立项手工激活档 / `/fenix-ready`）、与定时拾取/冻结同属「有意等待」不告警；并在「唤醒源全景」表的「定时拾取」行补注「（哨兵 manual 的 SPEC 永不参与到期检测）」

## 9. 人工步骤（不写成任务，仅供文档留痕）

> `~/.claude/skills/fenix-ready/SKILL.md` 位于仓库外（非本仓库 `skills/` 目录、亦非软链），**不可作为本仓库交付物**。`/fenix-ready` 放行时增「设为待激活」选项的改动须由人工在主树该文件手工补做——本 SPEC 只在 docs/help/06-governance.md（8.1）记录该人工步骤与改动要点，不进入 tasks 门禁对账。

## 10. 测试

- [ ] 10.1 tests/test_spec_scheduling.py：新增 `TestManualActivation` 测试类——覆盖 1.3 的谓词用例；增 `set_spec_start_after(..., 'manual')` 写入经 STATE.md 往返后 `get_spec_start_after` 返回 `"manual"`（哨兵持久化不折叠）；`check_scheduling_deadlines` 对 manual SPEC 多轮调用不唤起（不误判到期，对齐 D3）
- [ ] 10.2 tests/test_dashboard_api.py：新增 `/api/spec-activate` 端点测试——待激活 SPEC 激活成功（`start_after` 变 null + 写入 `scheduling_kick_request.json`）；非待激活（定时/null）返回 `{ok: false}` 且 STATE 不变；不存在 SPEC → 404；终态 → 403；并验证 `/api/spec-start-after` body `value: "manual"` 成功写入哨兵
- [ ] 10.3 tests/test_dashboard_api.py：列表摘要测试确认 `/api/specs` 每项含 `depends_on` 字段（值取自 STATE.md），且 `_ENTRY_SIG_KEYS` 含 `depends_on`（依赖变化触发索引失效）
- [ ] 10.4 tests/test_dashboard_evolution_api.py：`/api/evolution/accept` body `start_after: "manual"` 用例——接受成功，新建 SPEC 的 STATE entry `start_after` 为 `"manual"`（未被 parse_utc 拒绝）
- [ ] 10.5 运行 `python3 -m pytest tests/test_spec_scheduling.py tests/test_dashboard_api.py tests/test_dashboard_evolution_api.py -q` 全绿；如涉及 `tests/test_dashboard_data.py` / `tests/test_self_evolution.py` 的既有断言（如 spec_summary 字段集合、accept_item 参数），同步修正并跑通
