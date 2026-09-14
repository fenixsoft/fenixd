# fix-verify-contract-signal-semantics 设计

## Context

2026-09-08 verify_contract_missing 假信号事故（3 信号 / 3 admin run / 1 轮修复 b547eccb）。执行层 stop 顺序缺陷已修复；本变更收口信号层残余缺口：语义双载（missing 信号被覆盖确认旁路）与双发放大（前端 100ms 竞态 + 服务端无幂等）。调查定案见 admin_alerts.json 09-08 时间线与自省条目（09-09）。

## Goals / Non-Goals

- **Goals**：
  - 契约有效 + 覆盖确认 → 派发 `verify_contract_redraft`，`verify_contract_missing` 回归纯缺失语义
  - admin_monitor 全链路识别 redraft（severity / 指引 / 摄取 / 项目名提取）
  - 同项目同类型在途信号去重；前端同步防重入
- **Non-Goals**：
  - 不改动 admin run 的起草/自证流程本体（三段自证门、D4 权限边界原样）
  - 不做跨项目或跨类型的通用信号去重框架（仅本端点）
  - 不动 Popconfirm 交互形态与按钮文案（覆盖警示确认保留）

## Decisions

### D1 信号类型二分而非 evidence 标记（B）

新增 `verify_contract_redraft` 独立 signal_type，而非在 missing 信号上加 redraft=true 字段。理由：admin_monitor 消费按 signal_type 分派 severity 与处置指引（SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION 字典键），独立类型零侵入接入既有分派；evidence 字段是人读溯源通道，不让机器语义依赖它。

### D2 去重键 = signal_type + 项目名 + handled=false（D）

`_api_verify_yaml_autodraft_post` 派发前读 `AdminStore.read_all()`，过滤 `kind=SIGNAL && signal_type 相同 && handled=false && evidence 含「项目名=<name>」`。命中即不写、响应 message 注明在途。异类型互不抑制（missing 在途不挡 redraft——契约被修正后用户确认覆盖是新的合法意图）。已 handled 的历史信号不抑制（用户可再次请求重起草）。

### D3 前端 useRef 同步锁（D）

`setAutodraftLoading(true)` 到 Button loading 渲染生效存在 React 调度间隙（实证 100ms 内双击穿透）。`handleAutodraft` 入口用 `useRef<boolean>` 同步检查+置位，finally 复位。useRef 写读同帧原子，无渲染依赖。

### D4 admin_monitor 注册点（B）

四处同步：`SIGNAL_SEVERITY["verify_contract_redraft"]="major"`；`SIGNAL_RECOMMENDATION` redraft 专用指引（复核优先 + 显式授权才重起草 + 自证门不变）；`STORED_SIGNAL_TYPES` 追加（pm_engine 写入式摄取路径兼容，虽当前 redraft 仅 UI 源，注册保持管道一致）；`_detect_family_explosion` 的 evidence 项目名提取条件从 `stype == "verify_contract_missing"` 扩为双类型 `in` 判断。

## Risks / Trade-offs

- [redraft 信号处置仍可能判「有效不碰」→ 用户重起草意图未达成] → 处置指引明确「用户显式授权覆盖时方可重起草」，Administrator 有裁量权；本变更不强制 admin 必须重写契约（写好契约是 admin 能力问题，非信号语义问题）
- [去重读全量 store] → admin_alerts.json 现约 150KB，读放开销可忽略；不引入索引
- [前端锁在组件卸载后未复位] → useRef 随组件实例存亡，卸载即销毁，无泄漏

## Open Questions

（无——调查阶段已定案 B/D 范围，用户 2026-09-09 拍板 B+D 立项。）
