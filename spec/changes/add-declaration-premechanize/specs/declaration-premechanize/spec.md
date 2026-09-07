# Spec: declaration-premechanize

## ADDED Requirements

### Requirement: 晋升期机械软化

daemon 在 drafted → ready 晋升时，对声明段中 `kind: new/modify` 且路径命中确定性不可交付模式（gitignored / 仓库外）的条目，在 lint 之前机械改写 `kind → reference` 并落 dispute 审计（reasoning 前缀 `promotion-soften`），随后正常晋升；不再停留 `drafted + error` 等待人工修正。

#### Scenario: gitignored 声明晋升自动软化

- **WHEN** 某 drafted spec 的 tasks.md 声明段含 `- path: core/dashboard/static/dist/index.html` + `kind: modify`（dist 已被 .gitignore 排除），daemon 执行晋升
- **THEN** 该条目 kind 被改写为 `reference`，tasks.md 其余内容逐字保留
- **AND** `.fenix/dispute_audits.jsonl` 新增一条审计，verdicts 含该 element 且 reasoning 以 `promotion-soften` 开头、diff 含改写前后声明段
- **AND** spec 状态到达 `ready`（非 drafted+error），实现正常排队

#### Scenario: 仓库外声明晋升自动软化

- **WHEN** 某 drafted spec 声明 `- path: ~/configs/app.yaml` + `kind: new`（`~` 展开后不在仓库内），daemon 执行晋升
- **THEN** 该条目 kind 被改写为 `reference`，spec 正常晋升至 `ready`

#### Scenario: 非确定性形态不软化维持拒绝

- **WHEN** 某 drafted spec 声明含 `<spec_name>` 占位符路径、目录路径、主树不存在的 modify 路径或 basename 唯一命中的疑似笔误 new 路径
- **THEN** 这些条目 kind 不被改写
- **AND** 晋升 lint 照旧拒绝，spec 停留 `drafted` 且 STATE error 含对应违规消息

#### Scenario: 软化编排失败不阻塞晋升链路

- **WHEN** 软化过程中单条目 tasks.md 改写抛出异常（文件并发改写/格式漂移）
- **THEN** 该条目被跳过且记 warning，其余可软化条目继续
- **AND** 被跳过条目交由晋升 lint 照旧判定，晋升流程本身不因软化编排异常中断

### Requirement: lint 规则 6 仓库外路径

`lint_declared` 对 `kind: new/modify` 且路径解析后（`~` 展开、绝对/相对路径归一）不在项目根内的声明判违规拒绝晋升；`reference` 指向仓库外路径合法放行。

#### Scenario: 仓库外 new/modify 拒绝晋升

- **WHEN** 声明段含 `- path: ~/x.md` + `kind: new`，或 `- path: ../outside.md` + `kind: modify`
- **THEN** `lint_declared` 返回违规，消息含路径与「仓库外路径不可作为 new/modify 交付物」语义

#### Scenario: 仓库外 reference 放行

- **WHEN** 声明段含 `- path: ~/.claude/settings.json` + `kind: reference`
- **THEN** `lint_declared` 不对该条目返回违规

### Requirement: 守卫缺件确定性预分类

收工守卫判缺件后、派 dispute-judge 之前，daemon 先对缺件清单做确定性分类：命中不可交付模式的条目直接机械软化 + 审计（reasoning 前缀 `guard-preclassify`）+ 重跑守卫；全清则走既有放行分支且不派 judge run；剩余项才进入既有 dispute-judge 流程。

#### Scenario: 全部缺件命中确定性模式跳过 judge

- **WHEN** 实现 run 收工守卫判缺件，且缺件清单全部命中 gitignored/仓库外不可交付模式
- **THEN** daemon 逐条软化声明 kind → reference 并落审计，不派发 `dispute-judge-` run
- **AND** 守卫重跑通过后恢复 in-flight 并放行 merge

#### Scenario: 混合缺件仅剩余项进入 judge

- **WHEN** 缺件清单同时含确定性不可交付条目与真缺件条目（声明为 new/modify 且仓库内应存在但实现分支缺失）
- **THEN** 确定性条目被软化并从 judge 输入中移除
- **AND** dispute-judge run 的输入 missing 仅含剩余真缺件条目，后续按既有裁决四归宿处理

#### Scenario: 预分类失败回退既有 judge 流程

- **WHEN** 声明段解析失败或软化改写异常导致预分类不可用
- **THEN** 全部缺件按既有 dispute-judge 流程处理，行为与本 SPEC 落地前一致

### Requirement: 产出期教学注入

SPEC 起草指引（fenix-new skill 与 spec_gen tasks 工件 instruction）注入四类不可交付模式表：dist/构建产物 → 锚点文件 + `reference`；gitignored 路径 → 禁 `new/modify`；`~`/仓库外路径 → 禁 `new/modify`；`.fenix/` 运行时文件 → `reference`。

#### Scenario: tasks 工件指引含四类模式表

- **WHEN** 调用 `fenix_spec.py instructions tasks --change <name>`
- **THEN** 返回的 instruction 文本包含 gitignored、仓库外（`~`）、构建产物、`.fenix` 运行时四类模式的 kind 约定

#### Scenario: fenix-new skill 指引含四类模式表

- **WHEN** 阅读 `skills/fenix-new/SKILL.md` 的 tasks.md 生成指引节
- **THEN** 该节包含四类不可交付模式的 kind 约定表，并注明 daemon 晋升时对命中条目机械软化并审计留痕

### Requirement: 部署副本同源

`.fenix/core/deliverables.py` 与 `.fenix/schemas/spec-driven/schema.yaml` 部署副本与主树保持一致，保证 fenix-new lint 预检与 daemon 晋升审计同一份规则。

#### Scenario: 部署副本同步后预检与运行时同源

- **WHEN** 主树 `core/deliverables.py` 与 `schemas/spec-driven/schema.yaml` 完成修改并同步至 `.fenix/` 副本
- **THEN** 以 `sys.path` 指向 `.fenix/` 的 lint 预检能识别规则 6 并执行软化编排（`soften_unsatisfiable_declarations` 可导入），与 daemon 行为一致
