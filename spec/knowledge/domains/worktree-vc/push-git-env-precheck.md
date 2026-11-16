<!-- knowledge: capability=push-git-env-precheck rev=1 sources=spec/changes/evo-add-push-git-env-precheck -->

# 推送 git 环境预检与 N/A 短路

done→pushed 自动推送的 git 环境前置预检：remote 与目标分支缺失时推送不执行、以 N/A 专用字段终局短路留痕，连同续推通道的审批门与目标分支解析单源。推送引用与退避收敛语义见 [推送引用生命周期卫生](push-ref-hygiene.md)，退避续推消费通道见 [done 态推送退避续推](push-retry-recovery.md)，凭证环境见 [推送凭证环境确定性](push-credential-environment.md)。

## 现行规则

- 预检单点：`_git_push_ref` 执行 git push 前先探测 remote 存在性与目标分支存在性（`git remote` / `git rev-parse --verify`，纯本地探测不发网络），任一缺失即推送不执行。返回契约保持既有 `(bool, str)` 二元组：缺失时返回 `(False, "[push_na:no-remote|no-ref] <原因>")` 结构化标记，调用方（approve_push 主推、归档收口、分支尽力推）按 error 标记前缀分流；分支尽力推遇 N/A 按既有 best-effort 口径降级 info 级跳过，不写 spec STATE 失败留痕。
- N/A 终局留痕：预检不通过时推送结果记 push=N/A 并附原因，落 entry 专用持久字段（`_push_na` / `_push_na_reason`），不走 error 字段——不触达失败退避记账、不进退避重试、不计入重试计数、不发升级告警。持久化的目的：续推通道读该字段即终局跳过，daemon 重启后对同一 done spec 零重投递、零新失败记录。后续配置 remote 后由人工清除该字段或随 spec 归档自然消失，「环境修复后自动恢复推送」不是默认语义。
- 续推审批门：done 态续推通道在 `get_approve_mode` 生效值 manual（含配置缺省回退 manual 的未显式配置项目）且该 spec 无推送记账（push_attempts / 退避字段双源皆缺，即未经人工批准）时不自动补投推送——零记账 done spec 的续推投递即绕过审批语义。有推送记账（人工已批准推送后失败进入退避重试）的 manual spec 不受此门影响，与既有退避续推能力兼容；显式配置 auto 的项目行为不变。`gates.require_push_approval` 为全库无读取点的死键，审批语义以 approve_mode 为准。
- 目标分支解析单源：推送目标分支经 `_resolve_push_target_branch` 确定——配置键 `pm.push.target_branch` 优先（远程仅接收固定分支的项目），未配置按仓库当前分支探测（`git symbolic-ref --short HEAD`）；approve_push 主推与归档收口两处统一走该解析，不硬编码 main。
- 退避配置分级（`pm.push.retry_backoff_seconds` 缺失 DEBUG 静默用默认、非 None 非法形态 WARNING 回退、元素级非法静默回退）为既有行为，本能力仅以测试锁定防回归，语义见 [推送引用生命周期卫生](push-ref-hygiene.md)。

## 代码锚点

- 主实现：`core/pm_engine/engine.py`（`_git_push_ref` 预检与 `_PUSH_NA_PREFIX` 标记、`_record_push_na` 专用字段落盘、`_resolve_push_target_branch` 分支解析、approve_push 主推与归档收口两处 N/A 分流）
- 消费方：`core/event_bus.py` `_recover_done_push_retry`（N/A 终局门 + 审批门，置于既有门序之前）；`core/config.py` `get_approve_mode`（审批语义读取点）

## 溯源

- 2026-11-16 evo-add-push-git-env-precheck（spec/changes/evo-add-push-git-env-precheck/） — 新增本能力：推送前 remote/目标分支预检与 N/A 专用字段终局短路（废除「无 remote 退避耗尽写 error 并发 push_failed」旧形态）、续推通道审批门（manual 且零记账不自动补投）、推送目标分支去硬编码（配置键优先+当前分支探测）；退避配置分级仅测试锁定非新实现。动因实测：dsh-plugins 纯本地仓库（无 remote、分支仅 master）每日收尾推送连败 16 天，done 态续推通道装载后 4 个存量 done spec 集体必败并污染 STATE error 字段
