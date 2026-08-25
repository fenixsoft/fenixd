## ADDED Requirements

### Requirement: 审批模式配置

系统 SHALL 支持在 `.fenix/config.yaml` 的 `gates.approve_mode` 下配置审批模式，取值为 `"manual"` 或 `"auto"`，默认 `"manual"`。未配置或配置为 `"manual"` 时 SHALL 维持现有行为（SPEC 到达 `done` 后等待人工通过 `/fenix-approve` 审批推送）。配置为 `"auto"` 时 SHALL 启用自动审批（见「自动审批」需求）。`ConfigLoader` SHALL 校验该字段取值，非法值 SHALL 抛出配置错误。`config.template.yaml` SHALL 同步该字段及说明注释。

#### Scenario: 默认审批模式为 manual
- **WHEN** `.fenix/config.yaml` 中不存在 `gates.approve_mode` 字段
- **THEN** 系统按 `manual` 处理，SPEC 到达 `done` 后保持 `done` 状态等待人工审批

#### Scenario: 非法取值校验失败
- **WHEN** `gates.approve_mode` 被配置为 `"manual"` 或 `"auto"` 之外的值（如 `"always"`）
- **THEN** `ConfigLoader` 校验 SHALL 失败并抛出指明合法取值的配置错误

### Requirement: 自动审批

当 `gates.approve_mode` 为 `"auto"` 时，系统 SHALL 在某 SPEC 推进到 `done` 状态后自动执行审批：解析该 SPEC 的推送分支（优先 `STATE.md` 中记录的 `branch` 字段，否则为 `{worktree.implement_branch_prefix}/{spec_name}`，默认 `fenix/<spec_name>`），在项目根目录执行 `git push origin <branch>`，成功后将该 SPEC 状态推进到 `pushed` 并记录到 PROJECT_LOG；推送失败 SHALL 保留 `done` 状态、记录错误信息，且不静默通过，供人工 `/fenix-approve` 兜底。同一 SPEC 不得重复触发自动审批。

#### Scenario: auto 模式下 SPEC 到达 done 后自动推送并标记 pushed
- **WHEN** `gates.approve_mode=auto`，某 SPEC 验证通过并推进到 `done`，其分支为 `fenix/example-spec`，且 `git push origin fenix/example-spec` 成功
- **THEN** 系统 SHALL 自动执行该 push，并将该 SPEC 状态推进到 `pushed`，PROJECT_LOG 记录推送事件

#### Scenario: 推送失败时保留 done 供人工兜底
- **WHEN** `gates.approve_mode=auto`，某 SPEC 到达 `done`，但 `git push origin <branch>` 失败（如远端拒绝、分支不存在）
- **THEN** 该 SPEC 状态 SHALL 保持 `done`，`error` 字段记录推送失败原因，不自动标记 `pushed`

#### Scenario: 已 pushed 的 SPEC 不重复触发自动审批
- **WHEN** 某 SPEC 已处于 `pushed` 状态，事件循环再次扫描到它
- **THEN** 系统 SHALL 不再对其执行自动推送或状态转换

### Requirement: manual 模式保持人工门禁

当 `gates.approve_mode` 为 `"manual"`（或未配置）时，系统 SHALL 保持现有审批流程：SPEC 推进到 `done` 后停留在 `done` 状态，由用户通过 `/fenix-approve` 审查并执行推送；daemon 不得自动推送或推进状态。

#### Scenario: manual 模式下 done 状态等待人工审批
- **WHEN** `gates.approve_mode=manual`，某 SPEC 验证通过并推进到 `done`
- **THEN** 该 SPEC 状态 SHALL 保持 `done`，daemon 不执行任何 git push，也不推进到 `pushed`

### Requirement: Dashboard 可视化编辑审批模式

Dashboard SHALL 在「配置」页面提供审批模式（manual / auto）的可视化编辑，保存后写入 `.fenix/config.yaml` 的 `gates.approve_mode` 字段。保存成功 SHALL 提示「配置已保存，重启 daemon 后生效」。配置页 SHALL 展示当前生效的审批模式，并在 auto 模式选中时明示其会真实推送 git 分支到远端。

#### Scenario: 修改审批模式并保存
- **WHEN** 用户在配置页将审批模式从 manual 切换为 auto 并保存（POST /api/config）
- **THEN** `.fenix/config.yaml` 的 `gates.approve_mode` 更新为 `"auto"`，前端显示保存成功与「重启 daemon 后生效」提示

#### Scenario: 配置页展示当前审批模式与 auto 风险提示
- **WHEN** 用户打开某项目的「配置」页
- **THEN** 配置页 SHALL 展示当前 `gates.approve_mode` 取值，且选中 auto 时显示「auto 模式将在 SPEC 完成后自动推送 git 分支到远端」的提示
