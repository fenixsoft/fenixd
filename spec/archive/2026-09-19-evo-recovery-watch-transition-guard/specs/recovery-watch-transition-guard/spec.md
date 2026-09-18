# recovery-watch-transition-guard 增量规格

## ADDED Requirements

### Requirement: 状态过渡窗口内不误判 stale

recovery watch 与假就绪巡检在把某 spec 判定为 stale（未恢复推进）之前，MUST 检查是否存在『正在进行的 implementer→merge 过渡』：该 spec 有待合并分支（worktree_manager 侧 pending merge = 存在**归属该 spec** 的实现分支且其有**未并入 main 的提交**，`git rev-list --count main..<branch> > 0`；分支归属 MUST 由分支名解析出完整 spec 名后**全等比较**确定，MUST NOT 以前缀/子串判定——spec 名可互为前缀，如 `a-b` 与 `a-b-c`；亦 MUST NOT 以分支存在性判定——已合并的历史分支仍留存于仓库），或 implementer 成功收工的可观测痕迹落在判定缓冲窗口（`pm.recovery.transition_buffer_seconds`，缺省 60 秒）内时，MUST **顺延（保留观察项并推进其复查时刻）**本次判定，MUST NOT 升级 dispatch_stalled；顺延 MUST NOT 以「视为已恢复」关闭观察项，亦 MUST NOT 静默丢弃观察项（此后真实卡死将无人告警）。

该豁免 MUST 有上限：自 `max(该待合并分支未并入 main 的最新提交时间, 该 spec 成功收工痕迹时间)` 起算，超过 `pm.recovery.transition_grace_minutes`（缺省 **5 分钟**，且 MUST 小于复查间隔 `pm.recovery.followup_check_minutes`）仍未合并的待合并分支 MUST 回落既有 stale 判定，MUST NOT 使真实卡死被无限期洗为健康。起点 MUST NOT 只取提交时间——实现者末次提交可早于 succeed（事故实测间隙 243s），仅取提交时间会使豁免在复查到达前即被预先消耗（300s − 243s = 57s < 60s 缓冲窗）。

假就绪巡检（engine.py）侧的豁免为**条件性**：仅在能给出可复现触发场景（点名判据与其阈值）时方得施加（现行阈值 implementing/testing 卡死 ≈160min（run_timeout 默认 9000s + 600s 宽限）/ ready 滞留 20min，秒级过渡窗口不会触发）；给不出 MUST NOT 施加，既有 stale 告警语义不变。

#### Scenario: 成功-合并过渡窗口内复查顺延
- **WHEN** implementer 已 succeed 但 merge/状态机 transition 尚未完成（worktree 已清理、spec 仍处过渡态），recovery watch 恰好到点复查
- **THEN** 系统 MUST 顺延本次判定（保留观察项并推进复查时刻），MUST NOT 升级 dispatch_stalled，亦 MUST NOT 借此关闭观察项

#### Scenario: 真实 stale 仍被报出
- **WHEN** spec 确无未并入 main 的待合并分支（仅有已合并的历史分支，`rev-list --count == 0` 时应视同无待合并）、无近期成功收工痕迹，且超过复查时限仍未恢复推进
- **THEN** 系统 MUST 按既有语义升级 dispatch_stalled，行为与现状一致

#### Scenario: 前缀同名的他 spec 分支不算待合并
- **WHEN** spec `a-b` 自身无未合并分支，但仓库存在另一 spec `a-b-c` 的未合并分支（分支名形如 `fenix/a-b-c-<ts>`）
- **THEN** 该分支归属 MUST 解析为 `a-b-c`（全等比较），spec `a-b` 视同无待合并分支，MUST 按既有语义升级 dispatch_stalled，MUST NOT 因前缀同名被抑制

#### Scenario: 顺延期间观察项不得丢失
- **WHEN** 某 spec 因待合并信号被顺延判定
- **THEN** 观察项 MUST 仍在册且其复查时刻已推进（MUST NOT 因顺延被静默移除或关闭），使后续复查与有界性回落仍可发生

#### Scenario: implementer 成功即重置计时器（仅事件式方案适用）
- **WHEN** 实现采用**事件式**方案（design D2「事件式可选路径」：implementer succeed 信号到达时重置/顺延该 spec 的 recovery watch 计时器）且框架收到该信号
- **THEN** 该 spec 的 recovery watch 计时器 MUST 重置/顺延，避免旧登记在过渡窗口误触发
- **注**：本 SPEC 默认落 design D2 的**惰性求值**路径（不依赖该信号；两条判据在判定时求值）——未采用事件式方案时本 Scenario 不适用，验收 MUST NOT 以本 Scenario 断言惰性路径行为（否则会要求一个默认不存在的信号重置动作）