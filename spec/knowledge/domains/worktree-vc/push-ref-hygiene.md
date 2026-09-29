<!-- knowledge: capability=push-ref-hygiene rev=1 sources=spec/archive/2026-09-02-fix-push-ref-lifecycle -->

# 推送引用生命周期卫生

done→pushed 自动推送的引用纪律：main 为主交付物、分支尽力留痕、远端 SHA 去重、失败退避收敛与残痕清理。

## 现行规则

- main 为主交付物推送：done→pushed 的自动推送以 `git push origin main` 为成功判据；远端 main 不存在视为首次创建成功；非 fast-forward（远端分叉）判定失败并升级人工（发 push_failed 信号），禁止自动 force。feature 分支推送为尽力而为的留痕动作，其失败不影响 pushed 判定。
- remote-aware 去重：推送 feature 分支前以 `git ls-remote` 比对远端 SHA——一致视为已推送成功（无 push 命令发出或被去重短路，无 ERROR）；不同跳过分支推送并 WARN；远端不存在正常推送。本地分支不存在（merge-back 后已清理）时跳过分支推送（不产生 refspec 错误），以 main 推送结果承载内容。
- 失败退避收敛与升级：push 失败的 done spec 按指数退避（`pm.push.retry_backoff_seconds` 默认 [300, 900]）延迟重试，退避期内 recovery 重放跳过（不发 push 命令，日志记录退避等待）；连续失败达 `pm.push.max_retries`（默认 3）后停止自动重试，并发 push_failed 困境信号（severity=major）。
- 终态残痕清理：推送最终判定成功（含 SHA 去重判定）时清除该 spec 的 `error` 字段；提供幂等回填清理——pushed 终态且 error 以 "git push failed" 开头的记录，经 SHA 比对验证内容已在远端后清除，验证不到的保留并列日志清单。

## 溯源

- 史前复原（存量基线） — 推送核心为 main 优先、分支尽力、远端 SHA 去重；推送失败按指数退避收敛并回填执行残痕
- [2026-09-02 fix-push-ref-lifecycle](spec/archive/2026-09-02-fix-push-ref-lifecycle/) — 固化 main 成功判据与非 fast-forward 拒绝 force、ls-remote 去重与本地分支缺席跳过、指数退避与 push_failed 困境信号、终态残痕幂等回填清理
