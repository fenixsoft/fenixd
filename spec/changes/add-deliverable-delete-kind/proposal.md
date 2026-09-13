## Why

SPEC 声明「删除某个文件」这件事，今天没有任何一条校验路径 —— 写 `kind: modify` 会在收工守卫处**确定性误拦**（实现分支里文件已删，守卫判缺件打回），写 `kind: reference` 则**完全不校验**。唯一的合法写法恰好是最不设防的那种，于是「声明了删除」与「删除真的发生了」之间只剩作者的自觉。

2026-09-13 两起同类事故坐实了这个缺口：

- `.fenix/hooks/restart-daemon-when-idle.py` 的删除（`add-stale-code-selfheal` tasks 5.1/5.2/5.3）：三项全部勾选 `[x]`、spec 也已 pushed，但脚本与配置项原封不动还在主树 —— `.fenix/*` 被 gitignore，worktree 里根本没有这些文件，删除动作作用在空路径上静默 no-op，而声明写成 `reference` 意味着连「没做」都没有任何信号。收口后是被人工发现的。
- 仓库根 `__init__.py` 的删除（`fix-root-init-import-shadow`）：`modify` 会误拦，只能声明 `reference` 并**额外写一条回归断言**来兜住删除的强制性 —— 框架没提供的能力，由作者手工补了一个。

## What Changes

- **新增声明 kind `delete`**：语义为「本 change 的交付物是让该路径在合并后不存在」，只允许入库（git tracked）文件。守卫判定反转 —— 路径在实现分支 HEAD 仍存在即违规。
- **晋升 lint 新增四类拒绝**：`delete` 路径被 gitignore 排除、主树不存在（无可删）、是目录、在仓库外。
- **软化白名单排除 `delete`**：`classify_unsatisfiable` / `soften_declared_kind` 不得把 `delete` 降级为 `reference`（否则「该删」被静默改写为「仅审计」＝本缺口原样复刻）。
- **LLM 终审对 `delete` 条目机械拒绝 `reference` 裁决**：只允许 `typo` / `missing` / `unclear` 三个出口。
- **守卫返回签名由 `list[str]` 改为 `list[dict]`**（`{"path", "kind", "violation"}`，`violation ∈ {missing, undeleted}`）：三个消费点（dispute 匹配、LLM 终审、重派话术）按 kind 出词，避免「该删的还在」被说成「缺件」而误导人与 LLM。
- **派发前声明现实处方**为 `delete` 条目给出专属两种形态：主树存在 → 删除目标确认；主树不存在 → 无可删、疑似声明笔误并附 basename 候选。
- **产出期教学顶掉旧处方**：`skills/fenix-new/SKILL.md` 的 kind 语义段与不可交付路径表加入 `delete` 行，并明确「`.fenix/` 等 gitignored 运行时文件的删除**不能**由 SPEC 交付」——现有表格只教「运行时文件用 `reference`」，从没说这类删除交付不了，事故作者正是照着它走的。
- **BREAKING（内部契约）**：`_deliverable_gate_missing` 的返回类型变更，`dispatch.py` 内 4 个调用点同步改造。仅框架内部接口，不影响 SPEC 作者面。

## Capabilities

### New Capabilities

（无——`kind: delete` 是既有声明 schema 的扩展，不构成新能力。）

### Modified Capabilities

- `implementer-deliverable-gate`：声明段合法 kind 由三值扩为四值；收工时存在性校验对 `delete` 条目反判；守卫返回结构由路径列表改为带 kind 与违规类别的条目列表；派发前声明现实处方覆盖 `delete`。
- `declaration-premechanize`：晋升 lint 新增四类 `delete` 拒绝规则；机械软化与守卫缺件确定性预分类均把 `delete` 排除出软化目标；产出期教学注入更新为四类不可交付模式 + `delete` 语义 + 运行时文件删除不可交付的明示。
- `deliverable-declaration-triage`：守卫缺件 LLM 终审对 `delete` 条目拒绝 `reference` 归宿（防洗白），裁决机械执行不软化 `delete`。

## Impact

- **代码**：`core/deliverables.py`（kind 词表、提取归类、lint 规则、软化排除）、`core/pm_engine/verification.py`（守卫反判与返回结构）、`core/pm_engine/dispatch.py`（4 个消费点按 kind 出词、终审拒绝 `reference` 归宿）、`core/agent_runner/prompt_builder.py`（声明现实快照与处方段）。
- **声明契约**：`kind` 由 `new|modify|reference` 扩为 `new|modify|delete|reference`。存量 spec 不受影响（无 `delete` 声明即行为不变）。
- **Skill/文档**：`skills/fenix-new/SKILL.md` 的 kind 语义、不可交付路径模式表、Deliverables 工件 instruction。
- **测试**：`tests/test_deliverable_lint.py`、`tests/test_deliverable_gate.py`、`tests/test_deliverable_declaration_triage.py`、`tests/test_deliverable_declaration_premechanize.py`。
- **风险**：`delete` 与既有的「不可满足即软化」策略方向相反，软化路径若漏挡一处，`delete` 会被静默降级为空操作 —— 这正是本 SPEC 要消灭的形态，故防洗白防线是本 SPEC 的一等交付物而非附带。
- **非目标**：不新增 `kind: manual`／不做「收口时浮出人工待办」通道；不做 delete-or-move（重命名）语义；不改 Dashboard 展示（当前不渲染 kind）；不回改历史 spec 的既有声明写法。
