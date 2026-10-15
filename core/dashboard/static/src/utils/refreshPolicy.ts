// 刷新/心跳节奏常量单源（code-review item 73395d34f3de）：spec 列表页与 spec
// 详情页原先各自定义同值常量并靠「同 list.tsx」类注释互锚，调参改一处漏一处
// 会使两页刷新节奏漂移，收敛到本模块（对齐 @/utils/duration 的抽单源先例）。

// SSE 轻量通知（run_meta/refresh）后的 REST 重拉节流窗口
export const REFRESH_THROTTLE_MS = 500;
// 兜底心跳间隔（30s）：SSE 断线 / 事件丢帧时仍能校准
export const HEARTBEAT_MS = 30000;
