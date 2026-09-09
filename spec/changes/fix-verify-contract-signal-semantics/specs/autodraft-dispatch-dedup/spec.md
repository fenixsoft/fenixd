# UI 起草触发幂等治理（autodraft-dispatch-dedup）

## ADDED Requirements

### Requirement: 服务端在途信号去重

`POST /api/verify-yaml-autodraft` 在写入新信号前 MUST 检查 AdminStore 中是否已存在同项目、同 signal_type、未消费（handled=false）的同源信号；存在则 MUST NOT 重复写入，响应仍为 dispatched 且 message 注明已有在途请求（用户无需重复触发）。去重判定 MUST 以 `signal_type` + 项目名为键——`verify_contract_missing` 与 `verify_contract_redraft` 互不抑制。

#### Scenario: 在途信号期间重复触发不落盘
- **WHEN** AdminStore 已存在项目 fenixd 的未消费 `verify_contract_redraft` 信号，用户再次确认覆盖触发
- **THEN** 不写入新 SIGNAL 记录，响应 dispatched 且 message 含在途提示

#### Scenario: 已消费信号不抑制新触发
- **WHEN** AdminStore 中同项目同类型信号已 handled（处置完成）
- **THEN** 新触发正常写入新 SIGNAL 记录

#### Scenario: 异类型互不抑制
- **WHEN** AdminStore 已存在项目 fenixd 的未消费 `verify_contract_missing` 信号，此时契约被修正为可解析且用户确认覆盖触发
- **THEN** 正常写入 `verify_contract_redraft` 信号（missing 不抑制 redraft）

### Requirement: 前端触发防重入

设置页「AI 自动生成」按钮的 `handleAutodraft` MUST 使用同步 ref 锁防重入：入口处同步检查并置位（`useRef`），在途期间重复触发 MUST 直接返回不发出网络请求；请求结束（成功/失败）后 MUST 复位。该锁弥补 `setAutodraftLoading` 异步渲染前的竞态窗口（实证：2026-09-08 17:02 两次点击间隔 100ms 产生双信号双 admin run）。

#### Scenario: 竞态窗口内双击只发一次请求
- **WHEN** 用户在 loading 状态渲染生效前（<100ms）连续触发两次 onConfirm
- **THEN** 仅第一次触发发出 POST 请求，第二次被同步锁拦截，AdminStore 只落一个信号

#### Scenario: 请求结束后锁复位
- **WHEN** 一次触发请求完成（成功或失败）
- **THEN** ref 锁复位，后续点击可正常触发
