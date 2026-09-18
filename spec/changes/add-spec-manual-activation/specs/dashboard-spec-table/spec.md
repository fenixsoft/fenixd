## ADDED Requirements

### Requirement: 状态列展示「待激活」标记

SPEC 列表页 SHALL 在状态列对 `start_after` 为哨兵值 `manual` 的 SPEC 额外渲染「待激活」tag（与既有状态 badge、定时拾取标记并列），配色与语义对齐「人工介入等待」，SHALL 附 hover 提示说明「已设为手工激活，需人工激活后才会被拾取」。该标记 SHALL 在桌面表格与移动端卡片两种形态下均渲染。「待激活」标记的存在 SHALL NOT 改变状态列既有排序/过滤与行点击跳转行为。

#### Scenario: 待激活 SPEC 显示标记

- **WHEN** 某 SPEC 的 `start_after` 为 `manual`，打开项目 SPEC 列表
- **THEN** 该 SPEC 行状态列在状态 badge 旁额外显示「待激活」tag

#### Scenario: hover 展示激活说明

- **WHEN** 鼠标悬停于「待激活」tag
- **THEN** 显示提示文案，说明该 SPEC 需人工激活后才会被拾取

#### Scenario: 非待激活 SPEC 不显示标记

- **WHEN** 某 SPEC 的 `start_after` 为 null 或合法时间戳
- **THEN** 该 SPEC 行状态列不显示「待激活」tag

### Requirement: ready 且有依赖时状态列展示「前置依赖」标记

SPEC 列表页 SHALL 在状态列对 status 为 `ready` 且 `depends_on` 非空（非 null、非空串）的 SPEC 渲染「前置依赖」tag，鼠标悬停 SHALL 显示其依赖的 SPEC 名称（`depends_on` 的逗号分隔名列表，原样展示，解析口径与调度器 `_dependencies_satisfied` 一致）。该标记仅为展示，SHALL NOT 改变 `depends_on` 的调度语义。仅 status 为 `ready` 时展示——其它状态（drafted/blocked/终态等）SHALL NOT 展示该标记。

#### Scenario: ready 且有依赖显示标记

- **WHEN** 某 SPEC status 为 ready 且 `depends_on` 为 `spec-a,spec-b`，打开列表
- **THEN** 该 SPEC 行状态列显示「前置依赖」tag

#### Scenario: hover 展示依赖名

- **WHEN** 鼠标悬停于「前置依赖」tag
- **THEN** 显示依赖的 SPEC 名称（`spec-a`、`spec-b`）

#### Scenario: 无依赖不显示标记

- **WHEN** 某 SPEC status 为 ready 但 `depends_on` 为 null 或空
- **THEN** 该 SPEC 行不显示「前置依赖」tag

#### Scenario: 非 ready 状态不显示标记

- **WHEN** 某 SPEC 的 `depends_on` 非空但 status 非 ready（如 blocked）
- **THEN** 该 SPEC 行不显示「前置依赖」tag

### Requirement: 列表摘要接口暴露 depends_on 字段

Dashboard 列表接口 `GET /api/specs` 返回的每个 SPEC 摘要 SHALL 包含 `depends_on` 字段（值取自 STATE.md entry 的 `depends_on`，可能为 null）。该字段 SHALL 纳入列表摘要索引的条目指纹字段集（`_ENTRY_SIG_KEYS`），使 `depends_on` 变化时列表摘要缓存失效并重算，保证「前置依赖」标记不滞后于真实依赖。

#### Scenario: 摘要含 depends_on

- **WHEN** 请求 `GET /api/specs?project=<p>`
- **THEN** 每个 SPEC 摘要含 `depends_on` 字段，值与 STATE.md 一致

#### Scenario: 依赖变化触发摘要重算

- **WHEN** 某 SPEC 的 `depends_on` 由空变为 `spec-a`（STATE.md 变更）
- **THEN** 下一次列表请求返回更新后的 `depends_on`，「前置依赖」标记随之出现
