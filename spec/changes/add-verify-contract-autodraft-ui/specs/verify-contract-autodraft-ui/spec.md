# AI 起草人工触发入口（verify-contract-autodraft-ui）

## ADDED Requirements

### Requirement: AI 自动生成入口
设置页验证契约卡片 MUST 提供「AI 自动生成」按钮；点击确认后 MUST 异步派发 Administrator 起草请求并立即返回，MUST NOT 同步阻塞等待起草完成或轮询起草进度。

#### Scenario: 无契约时点击派发
- **WHEN** 项目无 `.fenix/verify.yaml` 或解析失败，用户点击按钮并确认
- **THEN** 请求立即返回派发成功，UI 提示 Administrator 将在巡检周期内拾取、结果见运维记录、完成后可重新加载

#### Scenario: 异步不阻塞
- **WHEN** 派发请求成功返回
- **THEN** UI 不发起任何对起草进度的轮询请求，编辑器保持可用（用户可继续手动编辑或重新加载）

### Requirement: 有效契约覆盖须二次确认
项目契约存在且可解析（`load_verify_contract` 非 None）时，点击按钮 MUST 弹出警示型确认（明示将覆盖现有内容与未保存编辑）；用户取消 MUST NOT 发出派发请求；用户确认后请求 MUST 携带覆盖意图（overwrite），后端凭此派发（人类显式授权优先于「有效契约不碰」边界）。契约缺失/解析失败时 MUST 使用普通确认（无覆盖警示）。

#### Scenario: 有效契约弹警示确认
- **WHEN** 项目存在可解析契约，用户点击按钮
- **THEN** 出现含覆盖警示的确认弹窗；取消则无任何网络请求

#### Scenario: 确认覆盖后派发
- **WHEN** 用户在警示弹窗中确认
- **THEN** 派发请求携带 overwrite 意图，后端正常派发信号

### Requirement: 派发端点语义
`POST /api/verify-yaml-autodraft?project=<name>`：未知项目 MUST 404；契约缺失/解析失败 MUST 写 `verify_contract_missing` SIGNAL（`AdminStore.append`，标注 `source=ui-manual` 与 overwrite 标记）并响应 dispatched；契约有效且无覆盖确认 MUST 响应 skipped 且不写信号；契约有效且带覆盖确认 MUST 派发。手动触发无关联 spec，信号 MUST 不强求 spec 字段且能被 admin_monitor 既有消费路径拾取。

#### Scenario: 未知项目 404
- **WHEN** 以不存在的项目名调用端点
- **THEN** 响应 404，不写任何信号

#### Scenario: 契约缺失派发信号
- **WHEN** 项目无契约文件时调用端点
- **THEN** 写入 `verify_contract_missing` SIGNAL 记录，响应 dispatched

#### Scenario: 有效契约无覆盖确认跳过
- **WHEN** 项目契约可解析且请求未带 overwrite
- **THEN** 响应 skipped（附「契约已有效」文案），不写信号

#### Scenario: 有效契约带覆盖确认派发
- **WHEN** 项目契约可解析且请求带 overwrite
- **THEN** 写入 SIGNAL 记录，响应 dispatched

### Requirement: 手动信号可溯源
手动派发的 SIGNAL 记录 MUST 标注 `source=ui-manual` 及 overwrite 意图，与验证链自动信号区分，供 Administrator 处置时判断触发来源与覆盖授权。

#### Scenario: 信号记录含来源标注
- **WHEN** 端点写入手动信号
- **THEN** 记录含 `source: ui-manual` 字段；带覆盖确认时含 overwrite 标记
