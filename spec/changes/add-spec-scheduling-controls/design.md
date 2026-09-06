## Context

现有调度链：spec 经 `StateMachine.add_spec` 注册进 STATE.md（entry 任意键 setdefault 透传），daemon 侧 Dispatcher 按 status/priority 筛选候选派发；`_dispatch_backoff_until` 是既有「时间门控」先例（到期前静默跳过、不写 STATE 防自触发）。人工冻结走 error 前缀「用户指令冻结：」+ 结构化 `frozen: True` 标记（state_machine.py `FROZEN_FIELD`），解冻官方通道为 `StateMachine.unfreeze_spec(spec, status=原状态)`（带 `frozen: False` 绕过 update_spec 冻结保护并清重验计数）。

**已发现的双轨不一致（本设计收编）**：dashboard `freeze_spec`（core/dashboard/data.py:288）绕过 StateMachine 统一入口，只写 `{status: blocked, error: 前缀+原状态}` 不写 `frozen: True`；其 `unfreeze_spec` 直接 `update_spec({"status": orig, "error": None})`——对带 `frozen: True` 的 spec（经 StateMachine.freeze_spec 冻结），update_spec 冻结保护会剥离 status（state_machine.py:441-449），导致「error 清空但 status 仍 blocked」的半死态。

daemon 主循环（fenixd.py `while self.running: sleep(1)`）已有独立计时段先例：30s 配置热更新、60s 恢复复查（recovery watch D6）、300s 自动归档，均为 try/except 包裹、异常记日志不中断主循环。

时间约定：全链 UTC 存储；dashboard 前端 dayjs 本地时区渲染（既有约定，勿裸切片直显）。

## Goals / Non-Goals

**Goals:**
- SPEC 定时启动：提交时（fenix-new）与提交后（dashboard）均可设置 `start_after`，到期前不拾取、到期后自动进入正常调度
- 冻结定时解冻：已冻结 spec 通过「冻结管理」弹窗在「永久冻结 ↔ 定时解冻」间切换，到期 daemon 自动解冻并恢复冻结前状态
- 冻结/解冻写入路径统一收编到 StateMachine 官方通道，消除半死态隐患

**Non-Goals:**
- 不做 cron 周期调度 / 重复执行（单次时间点门控）
- 不改优先级、依赖（depends_on）、退避（backoff）既有语义；`start_after` 仅叠加时间维度
- 不做定时启动/解冻的推送通知（按既有约定，自动兜底类事件静默，仅落运维记录）

## Decisions

### D1: 单一事实源 = STATE.md entry 字段
`start_after` 与 `frozen_until` 均存 STATE.md entry（ISO8601 UTC 带偏移，可空/null）。否决写入 `.spec.yaml`：spec 目录受 git 管理，运行时门控值频繁变更会污染版本库；dashboard 修改需走 spec 目录写+提交链路；且调度器只读 STATE.md。`add_spec`/`update_spec` 均任意键透传（已验证 setdefault/update 模式），状态机零改动。

### D2: start_after 门控 = 单一谓词 + 派发入口全覆盖
新增共享谓词（放 `core/state_machine.py` 模块级或新 `core/spec_scheduling.py`）：`start_after_pending(entry, now) -> bool`（解析失败视为不阻塞）。Dispatcher 候选筛选与 `engine._on_spec_ready` 入口均调用；未到期静默跳过（debug 日志），对齐 backoff 的「不写 error 不翻状态」防自触发设计。**所有派发路径必须过谓词**——尤其 boot recovery / 重派路径，防绕过（任务清单单列验证项）。

### D3: 到期检测挂 daemon 主循环（60s 独立计时段）
对齐 recovery watch 模式新增计时段：每 60s 调 `pm_engine.check_scheduling_deadlines()`：
1. 冻结 spec 的 `frozen_until` 已到期 → `StateMachine.unfreeze_spec(spec, status=原状态解析值)` 自动解冻（恢复冻结前状态、清 `frozen_until` 由解冻路径一并处理）；原状态解析复用「error 中『原状态 X』」约定，缺失时回退 ready
2. 非终态 spec 的 `start_after` 刚跨过当前时刻且状态可派发（drafted/ready）→ 唤起 `_on_spec_ready` 精触发

不做进程内一次性 Timer：主循环周期即兜底（daemon 重启天然恢复检测），幂等由「写前重读 STATE 确认仍处于待解冻/待派发态」保证；60s 粒度对「特定时间点之后拾取」语义足够。否决 Dashboard 进程持有 Timer：跨进程写 STATE 与 daemon watcher 竞争、dashboard 重启丢 Timer、多项目需多组 Timer。

### D4: 冻结/解冻路径收编 StateMachine 官方通道
dashboard `freeze_spec`/`unfreeze_spec` 改为委托 `StateMachine.freeze_spec`/`unfreeze_spec`（原状态记录并入 reason：`用户指令冻结：原状态 X · <reason>`；解冻 status 参数传解析出的原状态），消除半死态。冻结原因解析提为共享函数。PMEngine 显式委托门面如涉冻结算子须同步加委托（先例：verified 洗白治理）。

### D5: Dashboard API
- `POST /api/spec-start-after` `{project, spec, value: "<iso-utc>"|null}`：校验 ISO8601（非法 400）+ 终态拒绝；null 即清除
- `POST /api/spec-freeze-config` `{project, spec, mode, until?}`：`permanent`=清 `frozen_until`；`scheduled`=写 `frozen_until`（已过去→立即解冻而非留待 tick）；`unfreeze`=立即解冻
- `frozen_until` 更新不带 status 键，不触发冻结保护剥离；带 status 的解冻一律走 `unfreeze_spec` 官方通道

### D6: 前端（pages/projects/list.tsx + services/dashboard.ts）
- 行菜单：非终态 spec 增「设置拾取时间」（Modal：DatePicker 本地时区 + 清除定时按钮）；冻结 spec 增「冻结管理」（Modal：当前模式与原因展示 + 永久/定时 RadioGroup + DatePicker + 立即解冻按钮），现有「解冻 Spec」保留不动
- 列表：`start_after` 未到期行渲染定时 Tag（目标时间本地渲染 + 分钟级倒计时，随列表既有数据刷新节奏更新，不另起秒级定时器）
- 提交前 dayjs → UTC ISO 转换；时间解析/换算工具后端单点实现，前端只做本地时区输入与展示

### D7: fenix-new 流程更新
项目源 `skills/fenix-new/SKILL.md` 增补：`--start-after` 参数约定（绝对时间按本地 UTC+8 解释 / `+Nh`/`+Nm` 相对时长按提交时刻解释）、注册时经 `add_spec` attrs 写入 `start_after`、未指定时不写字段。Deliverables 声明为 `modify`（项目源在本仓库，守卫可精确对账）；安装副本 `~/.claude/skills/fenix-new/SKILL.md` 由任务同步保持一致（沿用 add-fast-track-mode 的「项目源 + 同步安装副本」模式）。

## Risks / Trade-offs

- [boot recovery/重派路径绕过 start_after 谓词] → D2 谓词单点 + 任务清单强制核对全部派发入口 + 测试覆盖 boot recovery 派发
- [dashboard 解冻对结构化冻结 spec 的半死态（存量双轨）] → D4 收编后消除；回归测试覆盖「StateMachine.freeze_spec 冻结 → dashboard 解冻 → status 正确恢复」
- [60s tick 异常中断主循环] → try/except 记日志，对齐既有计时段模式
- [自动解冻与冻结管理弹窗写竞争（用户恰在到期瞬间改时间）] → 全部经 StateMachine 文件锁原子写 + 写前重读确认；后写者覆盖、语义最终一致
- [时区误解] → 存储/比较全 UTC，仅展示层本地渲染；转述场景按既有约定转 UTC+8
- [start_after 与依赖/优先级叠加顺序] → 门控仅过滤时间维度，依赖未满足仍优先拦（`_dependencies_satisfied` 在前）；语义正交不冲突

## Migration Plan

字段为可空新增，存量 spec 零迁移；读侧对缺失字段按「无限制」处理。回滚 = 读侧忽略两字段（写入残留无害，`frozen_until` 非冻结态被忽略已有 spec 条款覆盖）。

## Open Questions

（无——模式已确认 full；时间粒度 60s、UTC 存储、弹窗交互均已与用户对齐）
