# 提案：推送步骤无远程环境预检短路

## 背景

框架推送步骤硬编码 git push origin main 且无任何 git 环境预检。dsh-plugins 是纯本地仓库（无 remote、分支仅 master），2026-10-14 起每日自省收尾推送连败 16 天（同文 WARNING）；2026-11-09 提交 b0890ad2f（fix-push-credential-env-and-retry-rearm）引入 done 态续推通道 _recover_done_push_retry 后，11-12 daemon 重启首次装载该代码，4 个存量 done spec 的发布推送集体必败，STATE.md 四条目 error 字段被污染并进入退避重试，3 次耗尽后还将各产一条 push_failed 升级告警。同批发现的近邻缺口：续推通道不查 gates.approve_mode，manual 审批语义被重启续推绕过（gates.require_push_approval 是全库无读取点的死键）。

## 目标

1. git 环境预检：推送前检查 remote 与目标分支存在性，无 remote 或无目标分支时标记 push=N/A 留痕短路——不执行 git push、不进退避重试、不写 error 字段。
2. 续推通道补门：_recover_done_push_retry 增加 approve_mode 门（manual 语义下不自动补投推送）；无远程环境的 done spec 走 N/A 留痕出口，不推进重试计数。
3. 目标分支去硬编码：推送目标分支按仓库实际分支探测或经配置键指定，approve_push 与归档收口两处裸推同覆盖。
4. 退避配置告警分级：pm.push.retry_backoff_seconds 键缺失时静默用默认退避（不再 WARNING），键存在但非法时保留 WARNING。

## 非目标

- 不实现自动建远程/自动改分支名（异地发布仍由人工配置 remote）。
- 不改动 approve_mode 的既有 done 时点判定逻辑。

## 附：存量数据修复提示

dsh-plugins STATE.md 四个 done 条目已被推送失败污染 error 字段（add-fenix-skill-provider-plugin、polish-dsh-plugins-ui、bridge-projects-inline-section、add-session-grouper-and-shell-polish），预检落地后由人工或维护动作清理污染 error、复位 push_attempts 记账，避免脏数据遗留。
