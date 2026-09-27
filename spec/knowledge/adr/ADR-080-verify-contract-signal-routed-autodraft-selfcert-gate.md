# ADR-080：验证契约缺失信号化自主起草，机械自证门把关

date: 2026-09-13
status: accepted

## Context

`.fenix/verify.yaml` 三段式契约（prepare/serve/ready）缺失或损坏时，验证链退回「打回 plan 修复」——plan 修不了基建，确定性死局只能烧轮次等 admin 升级。Administrator 具备起草高质量契约的能力，缺的是制度化触发通道与防「写个文件就算完」的自证门。

## Decision

- 基建缺口不重试、不打回 plan：契约缺失/占位符/解析失败在验证路径检测点直接写 `verify_contract_missing` 信号（复用 admin 信号通道），唤起 Administrator 自主起草；同 spec 信号节流防风暴，同项目契约只起草一次。
- 自证门：起草产物必须先经机械三段自证（validate：逐段 prepare → serve → ready 探测含鉴别力自检，独立薄 CLI 承载），全通才落位 `.fenix/verify.yaml`；草稿先写临时路径，防半成品被当有效契约。起草 2 轮上限，超限附草稿升级人工。
- 「有效契约」判定 = 可解析 + serve 段合法（轻量解析级，不在触发路径跑分钟级构建）；Administrator 权限边界即措辞：缺失即生成、明显失效可修且留痕、有效契约一律不碰。
- 人类显式授权可越过「不碰」边界：UI 二次确认后信号携带 `overwrite` 标记（source=ui-manual），后端对「有效契约且无 overwrite」的请求拒绝派发——admin 自主行为不得自行覆盖有效契约，人类权威行使须留痕。
- 收尾走既有权限：契约随 git 提交、spec 复位 ready、处置记录记 actions_taken；自证证「契约声明自洽」（三段可执行），不证「场景能过」——产品质量仍由验证链裁决。

## Consequences

- 确定性死局路径转为项目级一次性投资（契约起草）；自证门硬性拦截低质量起草，起草失败带草稿升级，人类只做判断。
- 手动 UI 触发与验证撞墙共用同一信号类型与消费路径，异步反馈诚实（明示巡检拾取周期，不伪装同步完成）。
