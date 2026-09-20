## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ApprovalModePanel.tsx
  kind: modify
- path: tests/test_config.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_start_after_gate.py
  kind: modify
- path: tests/test_start_after_scope.py
  kind: new
- path: docs/help/06-governance.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
```

> 说明：`core/dashboard/static/dist/**` 与 `.fenix/config.yaml` 均为 gitignored
> 运行时/构建产物，不入库、不进本声明段（`dist/` 由 `npm run build` 重建，
> 由框架验证链 prepare 阶段重建）。

## 1. 配置层：新增键与 getter（core/config.py）

- [x] 1.1 新增类常量 `VALID_START_AFTER_SCOPES = ["full", "dispatch"]`，紧邻既有
      `VALID_SPEC_REVIEW_MODES` 定义，附一行注释说明两档语义（`dispatch`=只约束实现派发
      链即旧行为；`full`=同时约束晋升/评审入口）。
- [x] 1.2 在 `_validate` 的 gates 校验段（`spec_review_mode` 校验之后）新增
      `start_after_scope` 校验分支：键存在且非 None 时，值不在 `VALID_START_AFTER_SCOPES`
      则 `raise ValueError`，错误信息含合法取值（措辞对齐既有三条：
      `"gates.start_after_scope must be one of ['full', 'dispatch']: <value>"`）。
- [x] 1.3 新增类方法 `get_start_after_scope(cls, config) -> str`，紧邻
      `get_spec_review_mode`；非法/缺失返回缺省 `"dispatch"`；docstring 说明缺省语义
      （回归 `fix-start-after-premature-pickup` 之前的旧行为）与两档差异。
- [x] 1.4 在 `tests/test_config.py` 中新增测试类（对齐 `spec_review_mode` 既有 4 例
      形态，`tests/test_config.py:847` 同款 `_write_valid(gates__<key>=...)` helper）：
      (a) 非法值 `"sometimes"` 被拒且异常含键名；(b) `full` / `dispatch` 两值均接受并
      回读到 `config["gates"]["start_after_scope"]`；(c) 未配置时
      `ConfigLoader.get_start_after_scope({})` 返回 `"dispatch"`；(d) 项目级显式
      `full` 经 `resolve_config` 生效（敏感路径：复用既有用例的 tmp HOME 隔离手法，
      **不得**读取真实 `~/.fenix/config.yaml`）。
      (e) 另加一例锁定**与 daemon 读路径同源**：`fenixd.py:326/:393` 把同一个
      `self.config` 同时传给 `PMEngine` 与 `EventBus`，两者都只调 getter、不缓存 scope，
      故热更新（`ConfigLoader.resolve_config_into`，`fenixd.py:796`，30s mtime）对
      「晋升/评审门」与「派发口」一致生效；本 SPEC 不新增第二份判定或缓存。该结论以
      一条用例锁定即可（如断言 getter 读的是入参 dict 而非模块级缓存），**不新增代码**。

## 2. 门控层：组合谓词与四处调用点

- [x] 2.1 在 `core/state_machine.py` 中新增模块级函数
      `start_after_blocks_promotion(entry, config=None) -> bool`（置于
      `start_after_pending` 之后）：实现为**纯组合表达式**
      `start_after_pending(entry) and ConfigLoader.get_start_after_scope(config) == "full"`。
      **MUST NOT** 在谓词内写 try/except——fail-open 由四处调用点既有 try/except 承担；
      若谓词吞异常，调用点 `except` 永不进入，`tests/test_start_after_gate.py:438/456/477`
      三条 fail-open 用例断言的 warning 将不可达（实测）。docstring 必须写明：
      (i) 仅用于**晋升/评审**入口——实现派发口 MUST 继续直接调 `start_after_pending`；
      (ii) `config=None` 等价 `dispatch`（不阻塞）；(iii) 异常不在此处吞，由调用点 fail-open。
      **MUST NOT** 修改 `start_after_pending` 的签名或语义（6 处调用点依赖其无条件性）。
- [x] 2.2 `core/pm_engine/engine.py` 的 `_on_spec_drafted`：把守卫内的
      `start_after_pending(entry)` 改为 `start_after_blocks_promotion(entry, self.config)`，
      并更新该处注释（把「fix-start-after-premature-pickup D1 无条件门控」改写为
      「受 `gates.start_after_scope` 条件门控，`full` 时行为同 fix-start-after-premature-pickup，
      `dispatch` 时回到该 SPEC 之前的旧行为」）。保留既有 try/except + warning 日志。
- [x] 2.3 `core/pm_engine/engine.py` 的 `_on_spec_reviewing`：同 2.2 改为
      `start_after_blocks_promotion(entry, self.config)`，注释同步更新。保留既有
      try/except fail-open 与 debug 日志措辞。
- [x] 2.4 `core/event_bus.py` 的 `_recover_one` **drafted 分支**：早退判定改为
      `start_after_blocks_promotion(entry, self.config)`；注释更新为受 scope 约束。
      保留「不产生 re-triggering promote 日志」的既有措辞与 debug 级别。
- [x] 2.5 `core/event_bus.py` 的 `_recover_one` **reviewing 分支**：同 2.4（reviewing 分支、
      `re-triggering spec_reviewing` 日志）。
- [x] 2.6 逐点自查实现派发口**未被改**：`core/pm_engine/engine.py` 的 `_on_spec_ready`
      （`start_after_pending(spec)`）与假就绪巡检豁免、`core/event_bus.py` 的
      `_recover_ready`、`core/pm_engine/dispatch/queue.py` 两处、`core/admin_monitor.py`
      一处 MUST 仍直接调用 `start_after_pending`（无条件）。用
      `grep -n "start_after_pending\|start_after_blocks_promotion" core/` 核对：新增谓词
      恰好出现在上述 4 个晋升/评审点，其余调用点不变。

## 3. Dashboard 后端受管键（config_admin.py）

- [x] 3.1 `_SOURCE_KEYS` 里在 `gates.spec_review_mode` 之后新增
      `"gates.start_after_scope"`；`_managed_key_sources` 中新增来源标注分支（
      `gates_raw.get("start_after_scope") in ("full", "dispatch")` → `sources[...] = "project"`，
      非枚举不标注，对齐 `spec_review_mode` 写法）。
- [x] 3.2 `read_config`（项目级文件回显）：对齐 `spec_review_mode` 分支，合法枚举才写
      `result["gates"]["start_after_scope"]`。
      **同一任务内 MUST 修掉既有缺陷（实测复现，本 SPEC 的门禁与设置页回显直接依赖它）**：
      `config_admin.py:431` 的 `result["gates"] = {"approve_mode": gates_raw["approve_mode"]}`
      是**整段替换**（非合并），项目级一旦显式配置了 `approve_mode`（本仓库
      `.fenix/config.yaml:139` 即如此），gates 的其余键在该分支后被丢弃——
      实测：项目级 `gates: {approve_mode: auto}` 时 `read_config` 返回
      `{'gates': {'approve_mode': 'auto'}}`，`promote_mode` / `spec_review_mode` 双双消失，
      新键 `start_after_scope` 也会同样消失（设置页回显退化为括号列出的两种缺省值）。
      修法（任选其一，MUST 在实现中落地并加断言）：把该行改为
      `result.setdefault("gates", {})["approve_mode"] = gates_raw["approve_mode"]`（对齐
      其余分支写法），**或**在函数尾部对 `result["gates"]` 统一按缺省补齐
      `promote_mode` / `spec_review_mode` / `start_after_scope` 三键（对齐 `:656-672`
      的读侧兜底语义）。
      缺省 dict（`"gates": {"approve_mode": "manual", "promote_mode": "auto"}`，两处
      `:336` / `:567`）中的 `start_after_scope` 缺省 `"dispatch"` 仍照原计划补
- [x] 3.3 `read_effective_config`（生效值回显）：经
      `ConfigLoader.get_start_after_scope(effective)` 回显（缺失/非法回退 `dispatch`，
      与 getter 单点同源），对齐 `spec_review_mode` 的 `result["gates"]["spec_review_mode"] = ...`
      写法。
- [x] 3.4 `_deep_merge_managed` 的 gates 合并段：把 `start_after_scope` 加入
      「任一键存在则确保 gates 为 dict」的判定条件，并新增
      `merged["gates"]["start_after_scope"] = patch["gates"]["start_after_scope"]` 分支
      （**缺此分支会被静默丢弃**——`promote_mode` / `spec_review_mode` 历史同坑）。
- [x] 3.5 `write_config` 前置校验：新增 `gates` patch 段的 `start_after_scope` 校验
      （非 None 且不在 `("full", "dispatch")` → `return fail(...)`，错误信息含合法取值）。
      同时在文件顶部 docstring 的补丁键列表（`含 llm / agents.models / gates.approve_mode`）
      补 `gates.start_after_scope`。
- [x] 3.6 `_SYNC_PAGE_KEYS` 的 `"approval"` 项扩展为
      `{"gates": ["promote_mode", "approve_mode", "spec_review_mode", "start_after_scope"]}`。
      **实测核对结论（2026-09-20）**：既有值为 `{"gates": ["promote_mode", "approve_mode"]}`
      （`config_admin.py:1634`）——**确实缺 `spec_review_mode`**，本任务 MUST 一并补上
      （缺键会导致「同步用户级设置」静默漏同步，`spec_review_mode` 自 add-spec-review-gate
      起即有此缺口）。
- [x] 3.7 在 `tests/test_dashboard_api.py` 新增用例：经 `read_config`（或既有测试同款
      入口）验证 (a) 未配置时 `gates.start_after_scope` 回显 `dispatch`；(b) 配置
      `full` 后回显 `full`；(c) `write_config` 写入 `full` 后读回一致；(d) `write_config`
      传非法值 `"sometimes"` 返回 `ok=False` 且不写盘；(e) `sync_config_from_user` 的
      `approval` 页能把 `start_after_scope` 从用户级同步到项目级——**该用例 MUST 与
      `:608` 既有断言的口径一致**：既有用例只 dumps `promote_mode` / `approve_mode`
      两键，故 `synced` 仍等于该两键字典；若用例改为额外 dumps `spec_review_mode` /
      `start_after_scope`，MUST 同步更新该 assert 的期望字典（不更新则既有断言转红）。
      (f) 项目级显式配了 `approve_mode`（本仓库形态）时，`read_config` 的 gates 段
      MUST 仍含 `promote_mode` / `spec_review_mode` / `start_after_scope`（锁定 3.2
      所修缺陷，防回归）。全部用 tmpdir 隔离，
      **不得**读取真实 `~/.fenix/config.yaml`。

## 4. Dashboard 前端（类型 + 审批页签控件）

- [ ] 4.1 `core/dashboard/static/src/services/dashboard.ts` 的 `GatesConfig` 接口新增
      `start_after_scope?: 'full' | 'dispatch'`，附注释说明两档与缺省 `dispatch`。
- [ ] 4.2 `ApprovalModePanel.tsx`：`useEffect` / `initialValues` 两处补
      `start_after_scope: config.gates.start_after_scope || 'dispatch'`；新增一个
      `Form.Item name="start_after_scope"`（`Radio.Group`，两个选项，每项带 Text 副说明），
      位置置于「SPEC 方案评审」与「推送审批模式」之间；`handleSave` 的 `gates` 载荷补
      该字段（**必须**保留既有三键，防整段覆盖丢失）。控件文案：
      - `dispatch` — 只约束实现派发（定时/待激活 SPEC 立即晋升并跑方案评审，实现等到点）
      - `full` — 同时按住晋升与评审（SPEC 停在草稿态，到期/激活才晋升并评审）
      `useEffect` 依赖数组补 `config.gates.start_after_scope`。
- [ ] 4.3 面板顶部说明文案补一句 scope 的作用（「定时拾取（start_after）的覆盖范围」）。
- [ ] 4.4 在 `core/dashboard/static` 下跑 `npx tsc --noEmit` 与 `npm run build`，两者均须
      通过（`dist/` 为 gitignored 构建产物，不入库）。
      **核对结论（2026-09-20 实测）**：该目录**改动前 tsc 即失败**（`npx tsc --noEmit`
      退出码 1、52 条 error，含 `ApprovalModePanel.tsx:25/27/39/59` 的
      `spec_review_mode does not exist on type 'GatesConfig'` 等本 SPEC 无关的存量错误）。
      `npm run build`（`max build`）实测退出码 0、可通过。故本任务的验收口径 MUST 表述为：
      **`npm run build` 必须通过**；`npx tsc --noEmit` 以「不新增错误」为通过判据
      （改动前 error 集合为基线，逐条比对），**MUST NOT** 以「tsc 全绿」作为验收条件
      ——否则本 SPEC 无法收口。`spec_review_mode` 那 4 条已属既有错误，随 4.1 补类型即可
      一并消除，可作为「不新增」的正向证据。

## 5. 回归测试适配与新增（tests/）

- [ ] 5.1 `tests/test_start_after_gate.py`：其 `_auto_config()` 当前返回
      `{"gates": {"promote_mode": "auto", "spec_review_mode": "never"}}`——在新缺省
      `dispatch` 下这些断言（未来 start_after 不晋升 / manual 不晋升）会失败。把
      `_auto_config()` 改为**含 `start_after_scope: "full"`** 的配置（保持既有断言
      原义：它们断言的是 full 档行为），并在该 helper docstring 写明「本文件锁定 full 档
      行为，dispatch 档用例见 `tests/test_start_after_scope.py`」。**MUST NOT** 靠删除或
      放宽既有断言让测试通过。
      **必须逐处替换的构造点（实测清点，仅改 helper 不够）**：
      (a) `_auto_config()` 本身（覆盖 `:128/:144/:155/:164/:172/:351/:364/:442` 八处）；
      (b) 4 处 `_make_engine(sm, proot, {})`（`:204` / `:222` / `:235` / `:464`）改传
      `_auto_config()`；(c) 2 处 `EventBus(self.state_path, self.sm, self.pm, {}, self.logger)`
      （`:261` / `:488`）改传 `_auto_config()`。原因：新谓词经 `self.config` 判 scope，
      gates 段缺失即等同 `dispatch`（不阻塞），实测这 6 处会使
      `test_future_start_after_not_promoted` / `test_manual_sentinel_not_promoted` /
      `test_future_start_after_no_dispatch` / `test_drafted_future_skips` /
      `test_reviewing_future_skips` / `test_manual_sentinel_drafted_skips` /
      `test_cleared_start_after_promotes_again` 等 11 条用例转红。
- [ ] 5.2 新增 `tests/test_start_after_scope.py`，覆盖 `dispatch` 档（缺省）行为，复用
      `test_start_after_gate.py` 的 fixture 构造手法（tmpdir 最小项目，不触真实项目
      STATE/用户级配置）：
      (a) `drafted` + 未来 `start_after` + `dispatch` → **照常晋升**（status 变 ready，
      `_on_spec_ready` 被调）；
      (b) `drafted` + `manual` + `dispatch` → 照常晋升（status 变 ready），且
      `_on_spec_ready` 被调（评审通过后）——「哨兵不自动实现」由 5.3 单独锁定；
      (c) `reviewing` + 未来 `start_after` + `dispatch` → 照常入队评审；
      (d) `_recover_one` 的 `drafted` / `reviewing` 分支在 `dispatch` 档下**不早退**
      （`handle_event` 被调，返回 True）；
      (e) `config=None` / 无 gates 段时谓词 `start_after_blocks_promotion(entry)` 返回
      `False`（缺省档不阻塞）——**该例只断言谓词返回值**；(e2) 另加一例断言
      `entry is None` 时谓词返回 `False`（`start_after_pending(None)` 内部
      `(entry or {})`，实测不抛、返回 False），用于锁定
      `tests/test_start_after_gate.py:228` 的 `test_entry_missing_no_early_return` 语义
      （SPEC 不存在时守卫不早退，交由 `promote_drafted` 的 not-found 拒绝）；
      (f) `full` 档下同四点多加一条对照组，证明开关双向生效
      （**注意 pass-through 路径如 `check_scheduling_deadlines` / kick 唤起的用例必须
      在 `full` 档下写**：它们在调用 handler 前已确认到期，dispatch 档下测不出门的存在）。
- [ ] 5.3 在 `tests/test_start_after_scope.py` 中新增用例锁定「实现派发口恒受门约束，
      与 scope 无关」：`ready` + 未来 `start_after`（或 `manual`），分别在 `dispatch` 与
      `full` 配置下调用 `_on_spec_ready` / `Dispatcher._process_queue` 候选筛选相关函数
      （沿用 `tests/test_spec_scheduling.py` 既有手法），两档均**不派发**。
- [ ] 5.4 在 `tests/test_start_after_scope.py` 中新增 fail-open 用例：monkeypatch
      `core.state_machine.start_after_pending` 抛异常，**断言谓词自身把异常向上传播**
      （谓词内 MUST NOT 吞；若断言为「返回 False」则与 2.1 的决策矛盾），且
      `_on_spec_drafted` / `_on_spec_reviewing` / `_recover_one` 三入口经各自
      try/except 走既有逻辑（不被新谓词吞掉），并如既有用例断言 warning 日志含
      「start_after 门控判定异常」（`tests/test_start_after_gate.py:438/456/477` 同款）。
- [ ] 5.5 跑 `python3 -m pytest tests/test_config.py tests/test_dashboard_api.py
      tests/test_start_after_gate.py tests/test_start_after_scope.py
      tests/test_spec_scheduling.py tests/test_event_bus.py tests/test_pm_promotion_gate.py -q`
      全绿；如有失败，逐条定位是「实现缺陷」还是「缺省档变更的预期差异」——后者须显式
      在对应用例中设 scope（不得放宽断言）。

## 6. 文档

- [ ] 6.1 `docs/help/09-config.md` 的 `gates` 键表新增一行
      `| start_after_scope | dispatch | full/dispatch | 热更新 |`，并在
      `gates.spec_review_mode` 说明段之后补 `gates.start_after_scope` 两档说明（一段）。
- [ ] 6.2 `docs/help/09-config.md` 的「Dashboard 设置页与配置键映射」表中
      「配置管理」行的 gates 键清单补 `gates.start_after_scope`。
- [ ] 6.3 `docs/help/06-governance.md` 的「SPEC 手工激活（待激活）」小节：把现有
      「**只拦派发、不拦晋升**」一句改写为「**拦不拦晋升取决于 `gates.start_after_scope`**」，
      说明两档下 `manual` 哨兵的行为差异，并明确「哨兵不自动实现的保证恒成立」（实现派发口
      无条件）。同时在「SPEC 方案评审门禁」小节的触发条件附近补一句：`start_after` 未到期
      的 SPEC 是否进入评审由 scope 决定。
