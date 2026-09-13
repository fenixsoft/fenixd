# 设计：verify.yaml 编辑器「AI 自动生成」按钮（verify-contract-autodraft-ui）

## Context

父机制 add-verify-contract-autodraft（full，实现中）建立了「验证撞墙 → verify_contract_missing 信号 → admin 起草 + 三段自证」的被动闭环；其信号写入走 `AdminStore.append`（先例 `verify_uniform_failure`，core/pm_engine/verification.py:1703），消费走 admin_monitor 通用「未 escalated 记录 → 唤起 Administrator」路径。本 change 给该机制补第四条触发通道：人工手动触发。设置页「项目简介」面板（ProjectProfilePanel.tsx）已有 verify.yaml 编辑器（GET/POST /api/verify-yaml + 模板端点），按钮是其操作区的自然延伸。

## Goals / Non-Goals

**Goals**：一键主动派发 AI 起草；覆盖授权语义清晰（人类显式授权可越过「有效契约不碰」）；异步反馈诚实（分钟级 admin run 不伪装成同步完成）。

**Non-Goals**：不做起草进度轮询/SSE 推送（运维记录页已有 admin 处置留痕）；不新增配置开关；不改父机制的起草流程与自证门；不做批量/定时起草。

## Decisions

**D1 信号类型复用 `verify_contract_missing`，手动信号加 `source=ui-manual` 标注。**
不新增信号类型——admin_monitor 既有通用消费路径直接拾取，落地顺序与父 SPEC 无强依赖（父 SPEC 先落地则 admin 侧手册齐备；先落地本 change 则 admin 收到信号按通用困境处置 improvising，可接受）。
手动触发无关联 spec：spec 字段留空，项目名经 evidence/detail 携带。风险点：admin_monitor 对无 spec 信号的既有处理需确认（部分告警形态要求 trigger 字段）——实现时验证，必要时最小适配（预期只是容缺，不改消费主路径）。

**D2 覆盖授权 = UI 侧二次确认，后端以 overwrite 参数记录意图。**
「有效契约一律不碰」是 admin 自主行为的边界；人类在 UI 显式确认覆盖 = 人类权威的直接行使， admin 凭信号中的 overwrite 标记获得覆盖授权。防线设两层：警示弹窗（明示覆盖现有内容与未保存编辑）+ 后端对「有效契约且无 overwrite」请求拒绝派发（响应 skipped，防止绕过 UI 直接打 API 误覆盖）。

**D3 契约「有效」判定 = `load_verify_contract` 非 None（轻量解析，不跑三段自证）。**
UI 点击路径不能触发分钟级构建（prepare 是三段自证的事）；解析级有效即足以把守「不覆盖有效契约」边界，运行时有效性由 admin 起草任务入口的判定与三段自证兜底（父 SPEC D4/D2）。

**D4 异步反馈文案诚实。**
成功响应 → message：「已提交 AI 起草请求，Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点重新加载查看新契约」。不轮询、不假装完成。404/网络错误 → message.error。

## Risks / Trade-offs

- [admin 未运行/巡检延迟，用户以为点了就生成] → 文案明示拾取周期与查看途径；运维记录页可核实信号是否被拾取。
- [重复点击重复派发] → 节流由 admin_monitor 既有同源信号节流约束（D2）；UI 侧按钮 loading 态降低连点概率，不做额外去重。
- [overwrite 信号被误用于自动链路] → source=ui-manual 是 admin 判断依据；自动链路（验证撞墙）从不携带 overwrite，父 SPEC 信号写入点不传该标记。

## Migration Plan

无迁移：纯新增端点与 UI 元素，存量行为零改动。回滚 = revert 提交。

## Open Questions

无——按钮语义（覆盖需二次确认）、异步反馈形态已在需求澄清阶段与用户确认。
