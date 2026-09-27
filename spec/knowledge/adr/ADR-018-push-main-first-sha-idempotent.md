# ADR-018：pushed 终态以远端内容为准，main 先行幂等重入

date: 2026-09-02
status: accepted

## Context

auto 模式推送以「创建远端 ref」语义发出，三类失效并存：重复触发被远端以 reference already exists 拒绝后 spec 停在 done 反复重放；本地分支被 merge-back 清理后推送引用已亡 refspec；main 长期不推使远端仓库不含真实交付物。pushed 判定与「内容是否真的在远端」脱钩，是推送管线的根基语义问题。

## Decision

- pushed 终态语义 = 内容确定在远端（SHA 可验证），而非「推送命令发出过」。
- main 先行为成功判据：`git push origin main` 成功即达 pushed；非 fast-forward 失败说明远端独立演进，属人工事件，自动 force 禁止，走退避升级。feature 分支推送仅在本地分支存在时执行，定位为审计留痕，失败不影响 pushed 判定。
- 幂等以 SHA 为准：推送前 `ls-remote` 比对远端 SHA，一致即视为已推送直接计入成功（重复触发零副作用）；远端存在但 SHA 不同则跳过分支推送并以 main 为准。
- 失败有界退避（默认 [300, 900]s、至多 3 次），退避期内重放跳过；超限发 push_failed 人工信号并停止自动重试；成功（含去重成功）清 error 与退避状态。
- recovery 重放进入推送前先查「已推送/退避等待」态，命中即跳过，消除周期重放源头。

## Consequences

- 推送动作可任意重入，重复触发与恢复重放均安全；main 承载内容、分支承载审计，远端审计链不完整的风险由 WARN 日志可溯。
- 远端分叉从静默卡死变为显式人工事件；代价是每次推送多一次 ls-remote 往返，其网络抖动与 push 同失败处理，不引入新失败类别。
