# Spec Delta: spec-status-actions-modal

## MODIFIED Requirements

### Requirement: 修改状态弹窗按状态渲染操作区块

点击「修改状态」MUST 打开弹窗，标题含 SPEC 名称。弹窗按当前状态条件渲染以下区块，全部走既有后端 API 与确认交互，MUST NOT 引入新的状态语义：

- **归档区块**：状态为 done 或 pushed 时渲染，含归档说明文案（目录移入 `archive/YYYY-MM-DD-<name>/`、STATE.md 条目保留）。点击归档 MUST 弹出确认，确认后调用既有归档 API，成功提示并刷新列表；失败展示错误信息。
- **冻结区块**：状态非 done 且非 pushed（未完成）时渲染。
- **晋升区块**：状态为 drafted 时渲染，含晋升说明（执行声明软化与 lint 检查；lint 违规停留 drafted）。点击晋升后调用既有晋升 API：成功提示已晋升 ready 并刷新；lint 违规或非 drafted 拒绝时展示违规明细/原因。
- **回炉区块**：状态为 `verified` 且该 SPEC 的 `error` 字段以 `task-gap:` 开头时渲染，含回炉说明文案——列出缺口任务 id 清单、说明回炉会把 SPEC 复位为 `ready` 并由 daemon 重新派发实现者承接剩余任务、说明缺口任务仍为未完成状态。点击回炉 MUST 弹出确认（危险操作，需明示"将重新派发实现"），确认后调用回炉 API：成功提示已复位 ready 并刷新；被拒绝时展示后端返回的拒绝原因。状态为 `verified` 但 `error` 非 `task-gap:` 前缀时不渲染该区块。

#### Scenario: 终态 SPEC 显示归档区块

- **WHEN** 对状态为 done（或 pushed）的 SPEC 打开修改状态弹窗
- **THEN** 弹窗渲染归档区块；点击归档并确认后 SPEC 目录移入归档目录，列表「已归档」视图可见该 SPEC

#### Scenario: 非终态 SPEC 不显示归档区块

- **WHEN** 对状态为 ready / implementing / testing / blocked / drafted 等未完成状态的 SPEC 打开修改状态弹窗
- **THEN** 弹窗不渲染归档区块

#### Scenario: drafted SPEC 显示晋升区块

- **WHEN** 对状态为 drafted 的 SPEC 打开修改状态弹窗
- **THEN** 弹窗渲染晋升区块；确认晋升成功后 SPEC 状态转为 ready；lint 违规时弹窗关闭并在页面展示违规明细，SPEC 停留 drafted

#### Scenario: 非 drafted SPEC 不显示晋升区块

- **WHEN** 对状态非 drafted 的 SPEC 打开修改状态弹窗
- **THEN** 弹窗不渲染晋升区块

#### Scenario: task-gap 滞留 SPEC 显示回炉区块

- **WHEN** 对状态为 `verified` 且 `error` 以 `task-gap:` 开头的 SPEC 打开修改状态弹窗
- **THEN** 弹窗渲染回炉区块，文案含缺口任务 id 清单与"将重新派发实现"的后果说明

#### Scenario: verified 但非 task-gap 不显示回炉区块

- **WHEN** 对状态为 `verified` 但 `error` 为空或以其它前缀开头的 SPEC 打开修改状态弹窗
- **THEN** 弹窗不渲染回炉区块

#### Scenario: 回炉确认后复位并刷新

- **WHEN** 在回炉区块点击回炉并确认
- **THEN** 调用回炉 API，成功后提示 SPEC 已复位 ready，列表刷新后该 SPEC 状态显示为 ready 且不再显示 task-gap 错误

#### Scenario: 回炉被拒绝时展示原因

- **WHEN** 回炉 API 返回拒绝（如 SPEC 已被其它操作改态、或转瞬进入冻结）
- **THEN** 弹窗/页面以 message.error 展示后端返回的拒绝原因，SPEC 状态保持不变
