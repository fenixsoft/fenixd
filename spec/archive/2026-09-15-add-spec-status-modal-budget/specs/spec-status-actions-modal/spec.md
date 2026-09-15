# spec-status-actions-modal 规格

## ADDED Requirements

### Requirement: 操作菜单收敛

SPEC 列表页（项目详情 SPEC 列表）每行的「更多」操作菜单 MUST 收敛为以下条目，按序排列：

1. 「修改状态」——打开修改状态弹窗（见下）；
2. 「呼叫 Admin 介入」；
3. 「调整优先级」（终态 done/pushed 置灰，语义沿用现状）；
4. 「设置拾取时间」（终态置灰，语义沿用现状）；
5. 分隔线；
6. 「删除 SPEC」（红色危险项）。

菜单 MUST NOT 再出现「晋升 ready」「冻结 SPEC」「解冻 SPEC」「冻结管理」「归档 SPEC」菜单项。已归档视图（archivedOnly=true）的菜单 MUST 保持现状：仅分隔线 + 「删除 SPEC」。

#### Scenario: 菜单项收敛后的完整清单

- **WHEN** 用户在未归档视图展开任一 SPEC 行的「更多」菜单
- **THEN** 菜单恰为「修改状态、呼叫 Admin 介入、调整优先级、设置拾取时间、分隔线、删除 SPEC」六项，不含任何状态类（晋升/冻结/解冻/冻结管理/归档）菜单项

#### Scenario: 终态置灰语义保持

- **WHEN** SPEC 状态为 done 或 pushed
- **THEN** 「调整优先级」与「设置拾取时间」置灰不可点，「修改状态」「呼叫 Admin 介入」「删除 SPEC」可点

#### Scenario: 已归档视图菜单不变

- **WHEN** 用户在已归档视图展开任一 SPEC 行的「更多」菜单
- **THEN** 菜单仅含分隔线与「删除 SPEC」，无「修改状态」入口

### Requirement: 修改状态弹窗按状态渲染操作区块

点击「修改状态」MUST 打开弹窗，标题含 SPEC 名称。弹窗按当前状态条件渲染以下区块，全部走既有后端 API 与确认交互，MUST NOT 引入新的状态语义：

- **归档区块**：状态为 done 或 pushed 时渲染，含归档说明文案（目录移入 `archive/YYYY-MM-DD-<name>/`、STATE.md 条目保留）。点击归档 MUST 弹出确认，确认后调用既有归档 API，成功提示并刷新列表；失败展示错误信息。
- **冻结区块**：状态非 done 且非 pushed（未完成）时渲染。
- **晋升区块**：状态为 drafted 时渲染，含晋升说明（执行声明软化与 lint 检查；lint 违规停留 drafted）。点击晋升后调用既有晋升 API：成功提示已晋升 ready 并刷新；lint 违规或非 drafted 拒绝时展示违规明细/原因。

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

### Requirement: 冻结区块覆盖冻结全生命周期

未完成 SPEC 的冻结区块 MUST 覆盖冻结全生命周期，吸收原「冻结管理」弹窗全部能力：

- **未冻结态**：显示「冻结」操作（永久冻结，daemon 停止调度），确认后调用既有冻结 API。
- **已冻结态**：显示当前冻结模式（永久冻结（人工解冻）/ 定时解冻 + 目标时间本地格式）、冻结原因（error 字段，如有）；提供：
  - 「立即解冻」按钮——调用既有解冻配置 API（unfreeze），成功后恢复冻结前状态；
  - 模式切换（永久 ↔ 定时解冻单选）+ 定时解冻时间选择器（showTime）——调用既有冻结配置 API，成功提示生效方式（定时到期 daemon 自动解冻 / 切换为永久冻结）。

#### Scenario: 未冻结 SPEC 可冻结

- **WHEN** 对未冻结的未完成 SPEC 打开修改状态弹窗
- **THEN** 冻结区块显示冻结操作；确认冻结后 SPEC 状态转为 blocked（用户指令冻结），daemon 停止调度，弹窗内转为已冻结态展示

#### Scenario: 已冻结 SPEC 展示模式并可立即解冻

- **WHEN** 对已冻结（含永久与定时两种）的 SPEC 打开修改状态弹窗
- **THEN** 冻结区块展示当前模式（定时解冻时含目标时间）与冻结原因（如有）；点击「立即解冻」并成功后 SPEC 恢复冻结前状态

#### Scenario: 已冻结 SPEC 切换永久与定时

- **WHEN** 在已冻结 SPEC 的弹窗中把模式从永久切换为定时并选定解冻时间提交
- **THEN** SPEC 的 frozen_until 更新为目标时间，到期由 daemon 自动解冻；反向从定时切回永久时 frozen_until 清除、改为人工解冻

### Requirement: 桌面与移动端入口一致

修改状态入口与弹窗 MUST 在桌面表格与移动端卡片两种形态下同等可用（共用菜单构建逻辑）。

#### Scenario: 移动端卡片菜单含修改状态

- **WHEN** 在移动端（<768px）展开任一 SPEC 卡片的「更多」菜单
- **THEN** 菜单与桌面一致含「修改状态」，点击打开同一弹窗
