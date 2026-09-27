<!-- knowledge: capability=recovery-watch-transition-guard rev=1 sources=spec/archive/2026-09-19-evo-recovery-watch-transition-guard -->

# 恢复监视过渡窗口守卫

implementer 成功到 merge 完成之间存在状态过渡窗口，恢复监视与假就绪巡检在该窗口内顺延 stale 判定，避免把正常过渡误判为卡死；豁免有上限，不洗白真实卡死。

## 现行规则

- 过渡窗口判定：recovery watch 与假就绪巡检把某 spec 判定为 stale（未恢复推进）之前，检查是否存在正在进行的 implementer→merge 过渡：该 spec 有待合并分支（worktree_manager 侧 pending merge = 存在归属该 spec 的实现分支且有未并入 main 的提交，`git rev-list --count main..<branch> > 0`；count 为 0 视同无待合并——已合并的历史分支仍留存于仓库，不得以分支存在性判定），或 implementer 成功收工的可观测痕迹落在判定缓冲窗口（`pm.recovery.transition_buffer_seconds`，缺省 60 秒）内。
- 命中即顺延：保留观察项并推进其复查时刻，不升级 dispatch_stalled；顺延不得以「视为已恢复」关闭观察项，亦不得静默丢弃观察项（此后真实卡死将无人告警）。
- 分支归属全等比较：归属由分支名解析出完整 spec 名后全等比较确定，不得以前缀/子串判定（spec 名可互为前缀，如 `a-b` 与 `a-b-c`——`a-b-c` 的未合并分支不得抑制 `a-b` 的 stale 告警）。
- 豁免有上限：自 `max(该待合并分支未并入 main 的最新提交时间, 该 spec 成功收工痕迹时间)` 起算，超过 `pm.recovery.transition_grace_minutes`（缺省 5 分钟，且须小于复查间隔 `pm.recovery.followup_check_minutes`）仍未合并的待合并分支，回落既有 stale 判定。起点不得只取提交时间——实现者末次提交可早于 succeed，仅取提交时间会使豁免在复查到达前即被预先消耗。
- 假就绪巡检（engine.py）侧的豁免为条件性：仅在能给出可复现触发场景（点名判据与其阈值）时方得施加；给不出则不施加，既有 stale 告警语义不变（现行阈值 implementing/testing 卡死 ≈160min、ready 滞留 20min，秒级过渡窗口不会触发）。
- 事件式可选路径：若实现采用 implementer succeed 信号到达时重置/顺延该 spec 的 recovery watch 计时器的事件式方案，收到该信号时计时器须重置/顺延；默认落惰性求值路径（判定时求值两条判据，不依赖信号），未采用事件式方案时该路径不适用。

## 溯源

- 2026-09-19 evo-recovery-watch-transition-guard — 新增待合并分支与成功收工缓冲的过渡窗口顺延、分支归属全等比较、有界豁免与巡检侧条件性豁免
