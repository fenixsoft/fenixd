# dashboard-spec-table 变更增量

## MODIFIED Requirements

### Requirement: SPEC 信息子行替换「错误」列

系统 SHALL 在 SPEC 列表页退役「行下信息子行」展示形态（桌面 `expandedRowRender` 子行与移动端 amber 软底信息行均不再渲染）。当某 SPEC 的状态消息字段（`STATE.md` 条目 `error` 字段，语义为告警/提示性信息）非空时，系统 SHALL 在该 SPEC 状态标签旁边渲染一个信息图标（antd `InfoCircleOutlined` 形态，warning 橙色，视觉约 14px）；消息为空或 `null` 时 SHALL NOT 渲染该图标。用户悬浮（桌面）或点按（触屏）该图标时，系统 SHALL 弹出提示层展示该消息的完整文本（可自动换行，SHALL NOT 截断），提示层内 SHALL 提供「清除」按钮：点击不触发整行导航，调用 `POST /api/spec-error-clear?project=<name>&spec=<name>` 将该 SPEC 的 `error` 字段置空（原子写回，不改动其余字段）；清除成功后图标随列表刷新消失，后续再次写入 `error` 时图标重新出现；清除失败在弹层内给出失败提示，不产生误导性成功感。信息图标与提示层 SHALL 在列表过滤、排序、自动刷新后保持正确渲染。fix-\* 树形子级展开/收起、整行点击进详情、名称 Why 悬浮提示、验证异常悬浮提示等既有交互 SHALL 零回归。

#### Scenario: 有信息时状态标签旁显示信息图标

- **WHEN** 某 SPEC 的 `error` 字段非空，查看 SPEC 列表
- **THEN** 该行状态标签旁渲染信息图标，行保持单行台账形态
- **THEN** 行下不再出现信息子行（桌面）或 amber 信息行（移动端）

#### Scenario: 悬浮图标显示完整信息

- **WHEN** 鼠标悬浮在有信息 SPEC 的信息图标上
- **THEN** 弹出提示层展示 `error` 完整文本，超宽自动换行不截断

#### Scenario: 无信息时不渲染图标

- **WHEN** 某 SPEC 的 `error` 字段为空或 null
- **THEN** 状态标签旁不渲染信息图标，无占位元素

#### Scenario: 弹层内清除信息

- **WHEN** 在提示层内点击「清除」按钮
- **THEN** 不触发行级导航，调用 `/api/spec-error-clear` 置空 `error` 字段
- **THEN** 列表刷新后信息图标消失；清除失败时提示失败而非成功

#### Scenario: 刷新/过滤/排序后图标仍正确显示

- **WHEN** 列表经过滤、排序、自动刷新后重新渲染
- **THEN** 有信息 SPEC 的图标仍在状态标签旁正确显示，无信息 SPEC 无图标

#### Scenario: 树形展开与行交互零回归

- **WHEN** 对 fix-\* SPEC 执行树形子级展开/收起、整行点击导航、点击信息图标本身
- **THEN** 树形展开收起正常；整行点击进详情正常；点击图标只弹提示层不导航

#### Scenario: 移动端卡片信息图标

- **WHEN** 移动端打开 SPEC 列表，某卡片对应 SPEC `error` 非空
- **THEN** 语义胶囊行状态胶囊旁渲染信息图标，点按弹出完整信息与「清除」
- **THEN** 原 amber 软底信息行不再渲染
