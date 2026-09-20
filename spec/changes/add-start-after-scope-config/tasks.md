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

- [ ] 1.1 新增类常量 `VALID_START_AFTER_SCOPES = ["full", "dispatch"]`，紧邻既有
      `VALID_SPEC_REVIEW_MODES` 定义，附一行注释说明两档语义（`dispatch`=只约束实现派发
      链即旧行为；`full`=同时约束晋升/评审入口）。
- [ ] 1.2 在 `_validate` 的 gates 校验段（`spec_review_mode` 校验之后）新增
      `start_after_scope` 校验分支：键存在且非 None 时，值不在 `VALID_START_AFTER_SCOPES`
      则 `raise ValueError`，错误信息含合法取值（措辞对齐既有三条：
      `"gates.start_after_scope must be one of ['full', 'dispatch']: <value>"`）。
- [ ] 1.3 新增类方法 `get_start_after_scope(cls, config) -> str`，紧邻
      `get_spec_review_mode`；非法/缺失返回缺省 `"dispatch"`；docstring 说明缺省语义
      （回归 `fix-start-after-premature-pickup` 之前的旧行为）与两档差异。
- [ ] 1.4 在 `tests/test_config.py` 中新增测试类（对齐 `spec_review_mode` 既有 4 例
      形态，`tests/test_config.py:847` 同款 `_write_valid(gates__<key>=...)` helper）：
      (a) 非法值 `"sometimes"` 被拒且异常含键名；(b) `full` / `dispatch` 两值均接受并
      回读到 `config["gates"]["start_after_scope"]`；(c) 未配置时
      `ConfigLoader.get_start_after_scope({})` 返回 `"dispatch"`；(d) 项目级显式
      `full` 经 `resolve_config` 生效（敏感路径：复用既有用例的 tmp HOME 隔离手法，
      **不得**读取真实 `~/.fenix/config.yaml`）。

## 2. 门控层：组合谓词与四处调用点

- [ ] 2.1 在 `core/state_machine.py` 中新增模块级函数
      `start_after_blocks_promotion(entry, config=None) -> bool`（置于
      `start_after_pending` 之后）：实现为
      `start_after_pending(entry) and ConfigLoader.get_start_after_scope(config) == "full"`，
      全包 try/except，任何异常返回 `False`（fail-open 放行）。docstring 必须写明：
      (i) 仅用于**晋升/评审**入口——实现派发口 MUST 继续直接调 `start_after_pending`；
      (ii) `config=None` 等价 `dispatch`（不阻塞）。
      **MUST NOT** 修改 `start_after_pending` 的签名或语义（6 处调用点依赖其无条件性）。
- [ ] 2.2 `core/pm_engine/engine.py` 的 `_on_spec_drafted`：把守卫内的
      `start_after_pending(entry)` 改为 `start_after_blocks_promotion(entry, self.config)`，
      并更新该处注释（把「fix-start-after-premature-pickup D1 无条件门控」改写为
      「受 `gates.start_after_scope` 条件门控，`full` 时行为同 fix-start-after-premature-pickup，
      `dispatch` 时回到该 SPEC 之前的旧行为」）。保留既有 try/except + warning 日志。
- [ ] 2.3 `core/pm_engine/engine.py` 的 `_on_spec_reviewing`：同 2.2 改为
      `start_after_blocks_promotion(entry, self.config)`，注释同步更新。保留既有
      try/except fail-open 与 debug 日志措辞。
- [ ] 2.4 `core/event_bus.py` 的 `_recover_one` **drafted 分支**：早退判定改为
      `start_after_blocks_promotion(entry, self.config)`；注释更新为受 scope 约束。
      保留「不产生 re-triggering promote 日志」的既有措辞与 debug 级别。
- [ ] 2.5 `core/event_bus.py` 的 `_recover_one` **reviewing 分支**：同 2.4（reviewing 分支、
      `re-triggering spec_reviewing` 日志）。
- [ ] 2.6 逐点自查实现派发口**未被改**：`core/pm_engine/engine.py` 的 `_on_spec_ready`
      （`start_after_pending(spec)`）与假就绪巡检豁免、`core/event_bus.py` 的
      `_recover_ready`、`core/pm_engine/dispatch/queue.py` 两处、`core/admin_monitor.py`
      一处 MUST 仍直接调用 `start_after_pending`（无条件）。用
      `grep -n "start_after_pending\|start_after_blocks_promotion" core/` 核对：新增谓词
      恰好出现在上述 4 个晋升/评审点，其余调用点不变。

## 3. Dashboard 后端受管键（config_admin.py）

- [ ] 3.1 `_SOURCE_KEYS` 里在 `gates.spec_review_mode` 之后新增
      `"gates.start_after_scope"`；`_managed_key_sources` 中新增来源标注分支（
      `gates_raw.get("start_after_scope") in ("full", "dispatch")` → `sources[...] = "project"`，
      非枚举不标注，对齐 `spec_review_mode` 写法）。
- [ ] 3.2 `read_config`（项目级文件回显）：对齐 `spec_review_mode` 分支，合法枚举才写
      `result["gates"]["start_after_scope"]`；并在该函数与 `read_effective_config` 的缺省
      dict（`"gates": {"approve_mode": "manual", "promote_mode": "auto"}`，两处）中把
      `start_after_scope` 缺省 `"dispatch"` 一并填好。
- [ ] 3.3 `read_effective_config`（生效值回显）：经
      `ConfigLoader.get_start_after_scope(effective)` 回显（缺失/非法回退 `dispatch`，
      与 getter 单点同源），对齐 `spec_review_mode` 的 `result["gates"]["spec_review_mode"] = ...`
      写法。
- [ ] 3.4 `_deep_merge_managed` 的 gates 合并段：把 `start_after_scope` 加入
      「任一键存在则确保 gates 为 dict」的判定条件，并新增
      `merged["gates"]["start_after_scope"] = patch["gates"]["start_after_scope"]` 分支
      （**缺此分支会被静默丢弃**——`promote_mode` / `spec_review_mode` 历史同坑）。
- [ ] 3.5 `write_config` 前置校验：新增 `gates` patch 段的 `start_after_scope` 校验
      （非 None 且不在 `("full", "dispatch")` → `return fail(...)`，错误信息含合法取值）。
      同时在文件顶部 docstring 的补丁键列表（`含 llm / agents.models / gates.approve_mode`）
      补 `gates.start_after_scope`。
- [ ] 3.6 `_SYNC_PAGE_KEYS` 的 `"approval"` 项扩展为
      `{"gates": ["promote_mode", "approve_mode", "spec_review_mode", "start_after_scope"]}`
      （**核对既有是否含 `spec_review_mode`，缺则一并补上**——缺键会导致「同步用户级设置」
      静默漏同步）。
- [ ] 3.7 在 `tests/test_dashboard_api.py` 新增用例：经 `read_config`（或既有测试同款
      入口）验证 (a) 未配置时 `gates.start_after_scope` 回显 `dispatch`；(b) 配置
      `full` 后回显 `full`；(c) `write_config` 写入 `full` 后读回一致；(d) `write_config`
      传非法值 `"sometimes"` 返回 `ok=False` 且不写盘；(e) `sync_config_from_user` 的
      `approval` 页能把 `start_after_scope` 从用户级同步到项目级。全部用 tmpdir 隔离，
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

## 5. 回归测试适配与新增（tests/）

- [ ] 5.1 `tests/test_start_after_gate.py`：其 `_auto_config()` 当前返回
      `{"gates": {"promote_mode": "auto", "spec_review_mode": "never"}}`——在新缺省
      `dispatch` 下这些断言（未来 start_after 不晋升 / manual 不晋升）会失败。把
      `_auto_config()` 改为**含 `start_after_scope: "full"`** 的配置（保持既有 23 例断言
      原义：它们断言的是 full 档行为），并在该 helper docstring 写明「本文件锁定 full 档
      行为，dispatch 档用例见 `tests/test_start_after_scope.py`」。**MUST NOT** 靠删除或
      放宽既有断言让测试通过。
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
      `False`（缺省档不阻塞）；
      (f) `full` 档下同四点多加一条对照组，证明开关双向生效。
- [ ] 5.3 在 `tests/test_start_after_scope.py` 中新增用例锁定「实现派发口恒受门约束，
      与 scope 无关」：`ready` + 未来 `start_after`（或 `manual`），分别在 `dispatch` 与
      `full` 配置下调用 `_on_spec_ready` / `Dispatcher._process_queue` 候选筛选相关函数
      （沿用 `tests/test_spec_scheduling.py` 既有手法），两档均**不派发**。
- [ ] 5.4 在 `tests/test_start_after_scope.py` 中新增 fail-open 用例：monkeypatch
      `core.state_machine.start_after_pending` 抛异常，`start_after_blocks_promotion`
      返回 `False`，且 `_on_spec_drafted` / `_on_spec_reviewing` / `_recover_one` 三入口
      仍走既有逻辑（不被新谓词吞掉）。
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
