# 契约自主起草派发去重
<!-- knowledge: capability=autodraft-dispatch-dedup rev=1 sources=spec/archive/2026-09-15-fix-verify-contract-signal-semantics -->

验证契约「AI 自动生成」UI 手动触发的幂等去重防线：服务端在途信号去重 + 前端触发防重入，防止一次意图派发多个信号、烧多份 admin run。

## 现行规则

- 服务端在途信号去重：`POST /api/verify-yaml-autodraft` 写入新信号前，检查 AdminStore 中是否已存在同项目、同 `signal_type`、未消费（`handled=false`）的同源信号；存在则不重复写入，响应仍为 `dispatched` 且 message 注明已有在途请求，用户无需重复触发。
- 去重键为 `signal_type` + 项目名：`verify_contract_missing` 与 `verify_contract_redraft` 互不抑制；已消费（handled）的同类型信号不抑制新触发。
- 前端触发防重入：设置页「AI 自动生成」按钮的 `handleAutodraft` 使用同步 ref 锁（`useRef`）——入口处同步检查并置位，在途期间重复触发直接返回、不发出网络请求；请求结束（成功或失败）后复位。
- 同步 ref 锁弥补 `setAutodraftLoading` 异步渲染生效前的竞态窗口：loading 状态可见之前（百毫秒级）的连续点击只有第一次发出 POST。

## 溯源

- 2026-09-15 fix-verify-contract-signal-semantics（spec/archive/2026-09-15-fix-verify-contract-signal-semantics） — 新增服务端在途信号去重与前端同步防重入锁（此前竞态窗口内双击产生双信号、双串行 admin run）
