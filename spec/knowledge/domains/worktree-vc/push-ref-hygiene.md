<!-- knowledge: capability=push-ref-hygiene rev=4 sources=spec/archive/2026-09-02-fix-push-ref-lifecycle,spec/knowledge/_inbox/done/v014-windows-write-path-hardening.md,spec/changes/evo-add-push-git-env-precheck,spec/changes/evo-wrapup-push-branch-guard -->

# 推送引用生命周期卫生

done→pushed 自动推送的引用纪律：目标分支为主交付物、分支尽力留痕、远端 SHA 去重、失败退避收敛与残痕清理。推送环境预检与 N/A 短路见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)。

## 现行规则

- 目标分支为主交付物推送：done→pushed 的自动推送以 `git push origin <目标分支>` 后远端 tip 前进为成功判据（推送前后远端 SHA 比对，空转不计成功，见 [推送交付完整性守护](delivery-push-integrity.md)），目标分支经解析单源确定（配置键 `pm.push.target_branch` 优先、缺省按仓库当前分支探测，见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)）；远端目标分支不存在视为首次创建（推送后远端出现该分支即 tip 前进）；非 fast-forward（远端分叉）判定失败并升级人工（发 push_failed 信号），禁止自动 force。feature 分支推送为尽力而为的留痕动作，其失败不影响 pushed 判定。
- remote-aware 去重：推送 feature 分支前以 `git ls-remote` 比对远端 SHA——一致视为已推送成功（无 push 命令发出或被去重短路，无 ERROR）；不同跳过分支推送并 WARN；远端不存在正常推送。本地分支不存在（merge-back 后已清理）时跳过分支推送（不产生 refspec 错误），以 main 推送结果承载内容。
- 失败退避收敛与升级：push 失败的 done spec 按指数退避（`pm.push.retry_backoff_seconds` 默认 [300, 900]）延迟重试，退避期内 recovery 重放跳过（不发 push 命令，日志记录退避等待）；连续失败达 `pm.push.max_retries`（默认 3）后停止自动重试，并发 push_failed 困境信号（severity=major）。
- 退避键缺省日志分级：`pm.push.retry_backoff_seconds` 未配置（含注释示例态）属设计内缺省——回退默认退避只记 DEBUG、不发 WARNING；非 None 的非法形态（字符串 / 长度不足 2 的 list / 负值、零值、布尔）保留 WARNING 留证。推送引擎 `_push_lock` 配置段按「缺省静默、非法留证」分级。
- 无 remote/无目标分支仓库预检短路：仓库未配 remote 或目标分支本地不存在时，推送执行前的环境预检直接短路——git push 不执行、记 push=N/A 专用字段终局留痕（不走 error 字段）、不进退避重试、不发升级告警；status 保持 done、dashboard problems 不计数，纯本地验收仓库零噪音；后续配置 remote 由人工清除 N/A 字段或随 spec 归档消失（语义见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)）。
- 终态残痕清理：推送最终判定成功（含 SHA 去重判定）时清除该 spec 的 `error` 字段；提供幂等回填清理——pushed 终态且 error 以 "git push failed" 开头的记录，经 SHA 比对验证内容已在远端后清除，验证不到的保留并列日志清单。

## 溯源

- 史前复原（存量基线） — 推送核心为 main 优先、分支尽力、远端 SHA 去重；推送失败按指数退避收敛并回填执行残痕
- 2026-09-02 fix-push-ref-lifecycle（spec/archive/2026-09-02-fix-push-ref-lifecycle） — 固化 main 成功判据与非 fast-forward 拒绝 force、ls-remote 去重与本地分支缺席跳过、指数退避与 push_failed 困境信号、终态残痕幂等回填清理
- 2026-11-16 v014-windows-write-path-hardening（spec/knowledge/_inbox/done/v014-windows-write-path-hardening.md） — 新增退避键缺省日志分级规则（未配置 DEBUG 静默、非 None 非法形态保留 WARNING）与无 remote 验收仓库 push_failed 属预期判读（status 保持 done、problems 不计数、配 origin 消除）
- 2026-11-16 evo-add-push-git-env-precheck（spec/changes/evo-add-push-git-env-precheck/） — 无 remote 仓库行为改道推送前环境预检 N/A 终局短路（废除「退避耗尽写 error 并发 push_failed」旧形态），推送目标分支去硬编码（`pm.push.target_branch` 优先+当前分支探测）；预检与续推审批门细节落新增能力页 push-git-env-precheck
- 2026-11-17 evo-wrapup-push-branch-guard（spec/changes/evo-wrapup-push-branch-guard/） — 目标分支成功判据从 push 命令执行成功升级为远端 tip 前进断言（push 后远端 tip 未前进的空转不再计成功）；断言细节、空转告警与启动领先对账落新增能力页 delivery-push-integrity
