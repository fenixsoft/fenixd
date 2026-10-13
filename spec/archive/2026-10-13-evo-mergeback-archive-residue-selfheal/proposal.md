## 背景

主树滞留归档半程状态（spec 目录删除已发生、收口提交未落库）时，任何无关 spec 的 merge-back 都会被 git 以「local changes would be overwritten」拒绝。既有顺延机制 60 秒×3 轮后熔断停机等人工，每次烧一个 admin 会话（实测样本 35/19/42+12 轮），同族告警一周 34 条。归档侧根因是收口提交 fail-open：commit_archive_move 失败只留 WARNING（fenixd.log 19:23:01Z fatal pathspec 实证），残留唯一消费者是 push 尾部收口，窗口内无 push 即无限悬置。

## 问题

两个缺口叠加：(1) 归档残留无周期收口，半程窗口可无限期存在；(2) merge-back 顺延链熔断前不做任何自愈评估，明摆着的「归档收尾未完」也照烧 admin 会话。

## 目标

merge-back 顺延熔断前接入只读自愈评估：脏文件特征命中「归档残留」（changes 侧删除 + archive 侧新增/未跟踪，且全部落在 spec/ 路径）时，由框架代为补提交归档收尾并立即重放 merge-back；同时给 spec_dir_inflight 顺延链补周期消费者，Timer 链中断（含进程重启）后仍能接手，把「必烧 admin 会话」降为自动放行。

## 非目标

- 不改真内容冲突车道（evo-add-codefix-mergeback-conflict-salvage 已覆盖）。
- 不改归档流程的异步蒸馏设计。
- 非归档类脏文件（源码 WIP 等）维持现状顺延→熔断等人工，绝不自动提交源码路径。