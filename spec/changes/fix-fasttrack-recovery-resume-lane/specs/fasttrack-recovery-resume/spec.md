# spec-fasttrack-recovery-resume

## ADDED Requirements

### Requirement: fast-track 派发入口消费恢复续做标记

`core/pm_engine/dispatch/queue.py` 的 `_run_agent_worker` fast-track 分支 MUST 与 implementer 分支**同源消费** `_recovery_resume` 恢复标记，判据与顺序 MUST 逐条对齐（`queue.py` implementer 分支既有实现为准）：

1. 读 `state_machine.read_one(spec_name)`；仅当 `_recovery_resume` 为真时取 `branch` 为 `resume_branch`；
2. `resume_branch` 非空时经 `wm.resolve_resume_site(spec_name, resume_branch)` 做载体三态解析（`WT_AVAILABLE` 原地 / `WT_REBUILDABLE` 从分支重建 / `WT_UNAVAILABLE` 降级），MUST NOT 自行拼装判定；
3. 无论解析结果如何，MUST 消费该标记（写 `_recovery_resume: None`）——标记为一次性，防后续扫描反复尝试续做；
4. `resume_wt` 非空时 MUST 经 `wm.mark_reused(spec_name, resume_wt, resume_branch)` 登记继承痕迹（供 prompt 注入），并打 INFO 日志说明「在保留分支上续做」；
5. `resume_wt` 为空（无标记 / 降级 / 零提交）时 MUST 打 WARNING 说明降级原因（含分支名），MUST NOT 静默降级。

MUST NOT 保留「入口无条件清除 `branch` / `implementer_run`」的现状——该现状使 `state_machine` 为 fast-track spec 保全的锚点在派发当刻即被抹除。清除动作 MUST 排在续做判定之后，且**仅在 `resume_wt is None` 时执行**。

#### Scenario: fast-track 续做命中时不抹锚点

- **WHEN** fast-track spec 经 recovery 保全分支后落 `ready`，STATE 为 `{status: ready, branch: "fenix/<spec>-<ts>", _recovery_resume: true}`，派发进入 fast-track 分支
- **THEN** 派发**不得**写出 `{"branch": null, "implementer_run": null}`；STATE 的 `branch` MUST 仍等于该保留分支

#### Scenario: 续做载体贯通到 runner

- **WHEN** 续做判定解析出可用载体（wt_path 非空）
- **THEN** 该 wt_path MUST 作为 `pre_wt_path` 传入 fast-track run，使 runner 不新建 worktree（`Creating worktree:` 日志 MUST NOT 出现）

#### Scenario: 续做命中时标记仍被消费

- **WHEN** 续做判定命中并完成派发
- **THEN** STATE 的 `_recovery_resume` MUST 被写为 None（一次性消费），后续扫描 MUST NOT 再次尝试续做

#### Scenario: 载体不可用降级并留痕

- **WHEN** `resolve_resume_site` 返回 `(None, None)`（分支不可解析 / 零提交 / 换壳失败）
- **THEN** 框架 MUST 打 WARNING 含 spec 名与分支名，随后按普通全新派发执行（此时**可以**清空旧锚点），MUST NOT 静默

#### Scenario: 无恢复标记的全新派发行为不变

- **WHEN** fast-track spec 无 `_recovery_resume` 标记（常规全新轮次）
- **THEN** 既有「清除旧锚点」行为逐字节保留（`branch`/`implementer_run`/`_repair_awaiting_remerge` 一并清零），与 implementer 分支的非续做路径一致

### Requirement: fast-track 恢复载体贯通至 runner

`AgentRunner.run_fast_track` MUST 接受 `pre_wt_path` 形参并透传至 `_execute_agent`（与 `run_implementer` / `run_repair` 同签名语义）：`pre_wt_path` 非 None 时 MUST NOT 创建新 worktree，且该路径 MUST 进入跨 attempt 复用判定与终态收割登记。

fast-track 的其余入口语义（impl- 前缀 run_id、预算计数、成功路径 merge 语义）MUST NOT 因本形参引入而改变。

#### Scenario: 传入载体不新建 worktree

- **WHEN** 调用 `run_fast_track(spec_name, pre_wt_path=<既有 worktree>)`
- **THEN** 该 attempt MUST 在既有 worktree 内运行，MUST NOT 触发 `worktree_manager.create`

#### Scenario: 不传载体时行为不变

- **WHEN** 调用 `run_fast_track(spec_name)`（缺省 `pre_wt_path=None`）
- **THEN** 行为与引入该形参之前逐字节一致

#### Scenario: 载体在 attempt 间隙失效时不白烧

- **WHEN** `pre_wt_path` 指向的目录在 attempt 间隙被外部清理，后续 attempt 复用该路径
- **THEN** runner MUST 检测路径失效并改走新建分支路径（MUST NOT 以 `[Errno 2]` 秒挂一次重试额度）

### Requirement: 继承注记注入 fast-track prompt

`prompt_builder` 构建 fast-track prompt 时 MUST 注入恢复续做继承注记，内容语义为「本 spec 的实现 run 曾因 daemon 重启/停机被中断；框架保留了你在分支上的已提交成果；本轮在原 worktree 内继续实现；检查当前分支已有提交与 tasks.md 勾选进度，从第一个未勾选项继续；不重做、不回滚」。

未登记复用痕迹（`get_reuse_record` 返回 None）时 MUST 返回空串，使 prompt 与现状逐字节一致。

注记来源 MUST 与 implementer 分支同源（同一 `_recovery_resume_note` 或等义单实现），MUST NOT 复制第二份文案实现。fast-track 既有 `_fast_track_reuse_note` 与恢复续做注记语义重叠（均为「延续已有成果」），同时命中时 MUST NOT 注入两条语义重复的段落。

#### Scenario: 续做轮 prompt 含继承注记

- **WHEN** fast-track 续做命中并经 `mark_reused` 登记继承痕迹
- **THEN** 构建的 prompt MUST 含说明「框架保留了你在分支上的已提交成果、从第一个未勾选项继续、不重做不回滚」的段落

#### Scenario: 无痕迹时零注入

- **WHEN** 无复用/续做痕迹（常规全新 fast-track run）
- **THEN** prompt MUST NOT 含该注记，且与现状逐字节一致

#### Scenario: 不重复注入语义重叠段落

- **WHEN** 同一次 prompt 构建中 `_fast_track_reuse_note` 与恢复续做注记同时可注入
- **THEN** MUST NOT 同时注入两条语义重复的「延续已有成果」段落

### Requirement: fast-track 派发出口的锚点处置矩阵完备

框架 MUST 对 fast-track 的**全部**派发出口逐一明确其「是否消费 `_recovery_resume` / 是否清锚点 / 是否保留现场」，MUST NOT 存在**无条件**抹除可续做锚点的出口。矩阵至少覆盖：

| 出口 | 位置 | 要求 |
|---|---|---|
| 首轮/常规派发 | `queue.py` fast-track 分支 | 消费标记；仅未命中续做时清锚点 |
| 规模预检降级 full | `fast_track.py:_downgrade_fast_track_scale` | 降级改写 mode 后重派 implementer；`branch`/`implementer_run` MUST NOT 被提前清空（降级后的 implementer 派发自会按其分支消费标记） |
| 结果文件缺失重派 | `fast_track.py` 结果读取失败分支 | 保持 `_recovery_resume` 语义；MUST NOT 新增清锚点 |
| 完成度判据/硬校验/verdict 失败重派 | `fast_track.py` 对应分支 | 同上 |
| 零变更哨重派 | `fast_track.py` 零变更处理分支 | 同上 |
| transient 终态保留 | `runner.py` fast-track 终态失败分支 | `keep_for_reuse` 保留现场；MUST NOT 清锚点 |
| repair lane fallback | `fast_track.py` / repair 链 | 保留现场交调度层；MUST NOT 清锚点 |

另有**两处**清锚点出口 MUST 在代码注释中固定其与 `_recovery_resume` 的区分，避免被误当作同类缺口：

- `engine.py` 的 auto-recovery（stuck implementing）：其判据已确认「**无存活子进程**」，属「确认 run 已死」的有意重置，MUST NOT 消费 `_recovery_resume`；
- `rollback.py` 的派发异常回滚：run **从未启动**，此时 `_recovery_resume` 尚未被消费、锚点亦非本轮产出，MUST NOT 消费该标记。

#### Scenario: 规模预检降级不清锚点

- **WHEN** 带 `_recovery_resume` 标记的 fast-track spec 在派发时被规模预检判为 `full` 档并降级
- **THEN** 降级路径 MUST NOT 清空 `branch`/`implementer_run`，且标记 MUST 在随后的 implementer 派发中被消费

#### Scenario: 重派类出口保留锚点

- **WHEN** fast-track run 因结果文件缺失 / 硬校验失败 / 零变更哨 / transient 终态失败而重派
- **THEN** 上述出口 MUST NOT 无条件清空 `branch`/`implementer_run`；现场保留语义（`keep_for_reuse` 等）保持不变

#### Scenario: auto-recovery 与异常回滚不消费标记

- **WHEN** spec 因 stuck implementing 被 auto-recovery 重置，或因派发异常被 rollback 回滚
- **THEN** 二者清锚点是既有有意行为；MUST NOT 因本变更而改为消费 `_recovery_resume`

### Requirement: fast-track 恢复续做可观测

续做命中、载体解析降级、出口清锚点三类事件 MUST 各有日志：

- 续做命中：INFO，含 spec 名、保留分支名、载体 worktree 路径；
- 载体解析降级：WARNING，含 spec 名、分支名与降级原因；
- 出口清锚点：INFO，含被清空的旧锚点值（与 implementer 分支的 `新轮次派发清除旧锚点` 同款）。

日志文本 MUST 使「本轮是恢复续做还是从零重做」可被直接判读，MUST NOT 仅凭「新建了 worktree」这一间接下游信号推断。

#### Scenario: 续做与重做在日志中可区分

- **WHEN** 一个 spec 在 daemon 重启后进入 fast-track 派发
- **THEN** 日志 MUST 出现「Resume dispatch ... on preserved branch ...」或「新轮次派发清除旧锚点 ...」二者之一，使本轮性质可直接判读
