# Design: fix-push-ref-lifecycle

## Context

approve_push（auto 模式在 done 时触发）只推 `fenix/<spec>-<ts>` feature 分支。三类失效相互独立又互相放大：

1. **重复创建被拒**：首次 done→pushed 推送成功后，recovery 的 verified→done 重放或后续事件再次进入 approve_push；此时推送仍以"创建远端 ref"语义发出（本地无 remote-tracking ref），GitHub 拒绝 `reference already exists`。失败后 spec 停在 done（未推进 pushed），下轮扫描再来——死循环且 error 字段被反复覆写。
2. **分支已亡**：部分路径 merge-back 后清理了本地分支，随后推送引用已消失的 refspec。
3. **主线缺位**：任何路径都未推送 main，origin/main 持续落后（当前 134 commits），远端仓库不含真实交付物。

## Goals / Non-Goals

**Goals:**
- pushed 终态 = 内容确定在远端（main 或分支 SHA 可验证），而非"推送命令发出过"
- 推送动作幂等可重入：重复触发零副作用
- 失败重试有界，超限升级人工
- 终态不带过时 error

**Non-Goals:**
- 不改 approve 门禁语义（manual 模式仍人工触发）
- 不做远端仓库清理（历史散落分支的 GC 另行人工处理）

## Decisions

- **D1 推送顺序：main 先行，分支尽力。** `git push origin main` 为成功判据（非 fast-forward → 失败走退避升级，因为本地 main 领先且无分叉时不会发生；若发生说明远端有独立演进，必须人工裁决，自动 force 禁止）。feature 分支推送仅在本地分支存在时执行，视为审计留痕，失败不影响 pushed 判定。
- **D2 去重以 SHA 为准。** 推分支前 `git ls-remote origin refs/heads/<branch>`：远端存在且 SHA 与本地一致 → 视为已推送，直接计入成功；远端存在但 SHA 不同 → 跳过分支推送并 WARN（以 main 为准）；远端不存在 → 正常推送。main 推送前同样比对，远端领先/分叉则进入失败退避并升级。
- **D3 失败退避与升级。** `pm.push.retry_backoff_seconds`（默认 [300, 900]）+ `pm.push.max_retries`（默认 3）。退避期内 recovery 重放直接跳过（spec 上记 next_retry_at 于 error 字段文本）；超限发 `push_failed` 困境信号（severity=major）并停止自动重试。成功（含去重成功）时清 error、清退避状态、推进 pushed。
- **D4 残痕回填。** 一次性维护脚本逻辑（幂等）：遍历 pushed 终态且 error 以 "git push failed" 开头的 spec，用 D2 的 SHA 比对验证内容已在远端后清 error；验证不到的保留并列清单日志。实现在 approve_push 同文件内供手动调用 + tests 覆盖。
- **D5 recovery 重放去重。** verified→done recovery 进入 approve_push 前先查该 spec 是否已处于"已推送"或"退避等待"，是则跳过（消除 30 分钟重放源头）；判断基于 error 字段内的退避标记与 D2 的 SHA 快查。

## Risks / Trade-offs

- [main 非 FF 时自动推送卡住] → 有意为之：远端分叉是人工事件，push_failed 信号保证可见性
- [feature 分支被跳过导致远端审计链不完整] → main 承载内容；分支跳过留 WARN 日志可追溯
- [ls-remote 网络抖动误判] → 与 push 同失败处理（退避重试），不引入新的失败类别

## Migration Plan

随 daemon 重启生效；首次运行时 D4 自动清理残痕。回滚 revert。无数据迁移。

## Open Questions

- 无
