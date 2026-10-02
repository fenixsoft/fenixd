# SPEC 定时拾取（start_after 门控）
<!-- knowledge: capability=scheduled-spec-pickup rev=5
     sources=spec/archive/2026-09-12-add-spec-scheduling-controls,spec/archive/2026-09-23-add-spec-manual-activation,spec/archive/2026-09-24-add-start-after-scope-config,spec/archive/2026-09-24-fix-start-after-premature-pickup,spec/archive/2026-09-25-fix-scheduling-kick-single-slot -->

SPEC 携带 `start_after` 锚点，在指定时间前不被自动推进调度；支持定时、永久待激活（哨兵）与无限制三态。

## 规则

- `start_after` 取值域三态，互斥：ISO8601 UTC 时间戳（定时拾取）/ 哨兵字符串 `manual`（待激活，永不到期）/ null（无限制）。`/fenix-new` 支持绝对时间（按本地时区 UTC+8 解释）与相对时长（`+2h`、`+30m`，按提交时刻解释），统一换算 UTC 经 `add_spec` 写入 STATE.md entry；未指定时为 null。哨兵判定大小写不敏感且忽略首尾空白（容错手工编辑）。
- 门控为实时评估而非一次性：未到期/哨兵 SPEC 被自动入口跳过时仅记 debug 日志，不写 `error`、不翻转状态、无任何持久化副作用；到期、被清空或激活后，下一次评估即正常推进，行为与从未设置过一致。
- 覆盖范围按入口分两类：
  - 实现派发口**无条件**覆盖：`ready` 态的 `_on_spec_ready`、派发队列候选筛选与恢复派发 `_recover_ready` 恒跳过未到期/哨兵 SPEC，与 scope 取值无关；
  - 晋升入口（`_on_spec_drafted`）与评审入口（`_on_spec_reviewing`）受配置键 `gates.start_after_scope` 条件覆盖（见 start-after-scope-config 能力）：`dispatch`（缺省）档照常晋升/评审，`full` 档一并按住。
- 门控施加在 handler 入口，且 handler 内**重读** STATE 取当前 entry（不依赖调用方传入的快照）；entry 读不到（SPEC 已删除/归档）时不早退，交既有链自然处理。
- 覆盖经 handler 入口的内部直调通道（`_on_spec_drafted` → `_on_spec_reviewing`）；覆盖面以 handler 入口为界——绕过 `_on_spec_reviewing` 直接调用 `SpecReviewManager.dispatch_review` 的通道（评审否决后的自动复评、人工 re_review）不在门控范围内，人工重评不得被定时门误伤。
- 人工显式放行入口不受定时门拦截：CLI `promote`、Dashboard 晋升、CLI `review`、Dashboard 重新评审对未到期 SPEC 照常放行；门控不下沉到共享晋升函数 `promote_drafted`（人工与自动同经此函数），只落在自动 handler 入口。同一「drafted + 未来 start_after」SPEC 经自动扫描被跳过、经人工晋升被放行，两种结论并存且各自符合语义。
- 恢复与扫描统一受门约束：daemon 启动恢复（event_bus 对 drafted/reviewing 的 re-trigger）与周期全量扫描在触发推进 handler 前先评估 `start_after`，不产生「re-triggering promote / re-triggering spec_reviewing」日志；早退与 `_recover_ready` 的 `start_after_pending` 早退同源（同一谓词、同一口径，不另写判据）；判定异常按 fail-open（不早退）处理，避免新闸门吞掉既有恢复能力。
- 到期接力通道：60 秒粒度的 `check_scheduling_deadlines`（drafted → 晋升链）+ 清空/激活时写入的即时唤醒信号（载体与契约见 scheduling-kick-signal 能力）；`_recover_ready` 不构成到期接力路径。唤醒信号成功写出时「到期→晋升/派发」延迟为秒级（主循环轮询粒度）；写出失败时退回周期扫描兜底（延迟上界 `schedule.poll_interval_minutes`，缺省 30 分钟），并按 scheduling-kick-signal 的回报契约如实告知调用方，不得表述为「即时派发」。
- 字段契约：写入路径（fenix-new 注册、dashboard 修改、evo 同意立项）校验格式，非法格式拒绝写入；早于或等于当前时间的值等价 null；终态（done/pushed）SPEC 的 `start_after` 不可被修改且不影响任何行为；读侧 `get_spec_start_after` 对哨兵 `manual` 原样返回字符串（不折叠为 null），null 与非法格式返回 null。
- Dashboard：spec 列表对未到期 SPEC 展示定时拾取标记（目标时间本地时区渲染 + 倒计时）；行操作菜单「设置拾取时间」可修改时间（本地时区输入转 UTC）或清除定时（置 null 立即恢复调度）；哨兵 `manual` 不渲染倒计时（渲染「待激活」标记），弹窗预填安全降级不报错不误清空；写侧同时接受哨兵值（设为待激活）与 null（清除/激活）。

## 溯源

- 2026-09-12 2026-09-12-add-spec-scheduling-controls（spec/archive/2026-09-12-add-spec-scheduling-controls） — 新增定时拾取：fenix-new 时间参数、调度器跳过与到期恢复、Dashboard 倒计时与修改、字段格式与边界语义
- 2026-09-23 2026-09-23-add-spec-manual-activation（spec/archive/2026-09-23-add-spec-manual-activation） — 哨兵值 `manual` 接入取值域：待激活展示与写侧、读侧不折叠 null、终态字段保护
- 2026-09-24 2026-09-24-add-start-after-scope-config（spec/archive/2026-09-24-add-start-after-scope-config） — 门控入口分两类：实现派发口无条件覆盖，晋升/评审入口受 scope 条件覆盖；恢复与扫描统一受门约束
- 2026-09-24 2026-09-24-fix-start-after-premature-pickup（spec/archive/2026-09-24-fix-start-after-premature-pickup） — 增补人工放行不受门拦截、内部直调通道覆盖边界（以 handler 入口为界）、实时评估与到期接力延迟口径
- 2026-09-25 2026-09-25-fix-scheduling-kick-single-slot（spec/archive/2026-09-25-fix-scheduling-kick-single-slot） — 到期接力改经即时唤醒信号并区分成败口径：成功秒级唤起，失败退扫描兜底且必须如实回报
