<!-- knowledge: capability=spec-status-actions-modal rev=2 sources=spec/archive/2026-09-15-add-spec-status-modal-budget,spec/archive/2026-09-19-fix-impl-tasks-completion-gate -->

# 状态变更操作弹窗

SPEC 行「更多」菜单收敛与「修改状态」弹窗：按当前状态条件渲染归档/冻结/晋升/回炉操作区块。

## 现行规则

- 菜单收敛：SPEC 列表每行「更多」操作菜单恰为六项、按序排列——「修改状态」「呼叫 Admin 介入」「调整优先级」（终态 done/pushed 置灰）「设置拾取时间」（终态置灰）分隔线「删除 SPEC」（红色危险项）；不再出现「晋升 ready」「冻结 SPEC」「解冻 SPEC」「冻结管理」「归档 SPEC」菜单项。
- 已归档视图（archivedOnly=true）菜单保持现状：仅分隔线 + 「删除 SPEC」，无「修改状态」入口。
- 入口一致：修改状态入口与弹窗在桌面表格与移动端卡片两种形态下同等可用（共用菜单构建逻辑）。
- 修改状态弹窗标题含 SPEC 名称，按当前状态条件渲染以下区块，全部走既有后端 API 与确认交互，不引入新的状态语义。
- 归档区块：状态为 done 或 pushed 时渲染，含归档说明文案（目录移入 `archive/YYYY-MM-DD-<name>/`、STATE.md 条目保留）；点击归档弹出确认，确认后调用既有归档 API，成功提示并刷新列表，失败展示错误信息。
- 冻结区块：状态非 done 且非 pushed（未完成）时渲染，覆盖冻结全生命周期——未冻结态显示「冻结」操作（永久冻结，daemon 停止调度），确认后 SPEC 转为 blocked（用户指令冻结）；已冻结态显示当前冻结模式（永久冻结（人工解冻）/ 定时解冻 + 目标时间本地格式）与冻结原因（error 字段，如有），提供「立即解冻」（调用既有解冻配置 API，成功后恢复冻结前状态）与模式切换（永久 ↔ 定时解冻单选 + 定时解冻时间选择器，定时到期 daemon 自动解冻，切回永久时清除 frozen_until、转为人工解冻）。
- 晋升区块：状态为 drafted 时渲染，含晋升说明（执行声明软化与 lint 检查；lint 违规停留 drafted）；晋升成功提示已晋升 ready 并刷新；lint 违规或非 drafted 拒绝时展示违规明细/原因。
- 回炉区块：状态为 `verified` 且该 SPEC 的 `error` 字段以 `task-gap:` 开头时渲染——列出缺口任务 id 清单，说明回炉会把 SPEC 复位为 `ready` 并由 daemon 重新派发实现者承接剩余任务、缺口任务仍为未完成状态；点击回炉弹出确认（危险操作，明示「将重新派发实现」），确认后调用回炉 API：成功提示已复位 ready 并刷新；被拒绝时展示后端返回的拒绝原因，SPEC 状态保持不变。状态为 verified 但 `error` 非 `task-gap:` 前缀时不渲染该区块。

## 溯源

- 2026-09-15 add-spec-status-modal-budget（spec/archive/2026-09-15-add-spec-status-modal-budget） — 更多菜单收敛为六项；建立修改状态弹窗按状态渲染归档/冻结/晋升区块，冻结区块吸收原「冻结管理」弹窗全部能力
- 2026-09-19 fix-impl-tasks-completion-gate（spec/archive/2026-09-19-fix-impl-tasks-completion-gate） — 新增 verified + task-gap 前缀的回炉区块：缺口任务清单、复位 ready 重新派发的危险确认与拒绝原因透出
