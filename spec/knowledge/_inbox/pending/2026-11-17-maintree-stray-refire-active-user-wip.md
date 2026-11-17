# maintree_stray_wip_stale 第 8 度复发：活跃用户主树直改 WIP 的再升级噪音（2026-11-17）

## 结论（当前事实）

- **本次告警是误报噪音，清单为真实用户 WIP**：14 个 tracked 文件改动自述「2026-11-16 用户需求/指令」（DshNewSessionButton 图标化、SPEC 列表配置钮、台账列宽双档、evolution 异步 accept 等），是用户经 dsh web 会话直改主树的在途工作，不是无主陈旧散件。
- **两个裁决选项均不可执行（硬约束）**：
  - `commit_stray_wip` 必断链：`core/dashboard/static/src/pages/overview/components/ProjectTable.tsx` import `@/hooks/useMediaQuery`、`core/dashboard/static/src/pages/projects/list.tsx` 与 `DshNewSessionButton.tsx` import `@/components/DshIconButton`，这两个新文件均 untracked 且不在信号清单内；只提交清单内 tracked 文件会产生 HEAD 断链提交（verify 链与新 worktree 播种即坏）。
  - `untrack_stray_wip` 对源码清单属仓库损伤（`git rm --cached` 出库真实源码 + ignore 吸收 = 不再版本控制）。
- **本次处置＝零触碰 + 显式跟踪项收口**（合规于 iron rule 10 的第三出口）：未执行任何 git 写；开工前后 `git status --porcelain` 哈希一致。
- **复发计数**：同文件 maintree_stray_wip_stale 已 8 度处置（历史 7 轮）。第 1–7 轮全部由归属者自行提交自愈，零轮实际执行清单提交或 untrack——与 worktree-vc 能力页记载的复发噪音形态完全一致。

## 根因（框架侧缺口，待立项）

1. **「归因出现→消失」转换再升级**：会话归因命中轮把指纹计时条目整体出册并销毁升级标记（同指纹一次性去重失效）；会话退场后的无主分支以当轮时刻重新建档、重起算 30 分钟宽限，于是同一副本 WIP 每次会话开合都烧一条 admin run。
2. **dsh web 结构性归因盲区**：dsh 每消息一次性 `claude -p` 执行形态使「worktree 分支 diff」与「主树活交互会话」两探测源在告警时点确定性零命中——最需要归因的形态恰是归因器看不见的形态。
3. **缺第三处置出口**：注册表只有 commit / untrack 两选项，对「活跃用户源码 WIP」既不能提交（断链）也不能出库（损伤），只能由 admin 自由裁量零触碰。

## 建议立项（供下一轮 distill / self-review 评估）

- 方案 A（最小）：归因命中清计时时**保留升级标记**，仅内容指纹变化才清除；归因消失轮重建档时继承原 first_seen。
- 方案 B（补充）：检测到活跃 dsh web 会话（进程级，不依赖 per-message 探测）时，对同指纹告警设冷却窗口或降级 info。
- 方案 C（出口补齐）：注册表新增 `track_stray_wip`（活跃用户 WIP 留痕跟踪，零触碰收口），使 admin 不必每次自由裁量。
- 三者可合并为一个小 spec；证据：本文件 + `.fenix/admin_alerts.json` 指纹 179403198762b93c + 2026-11-16 同型 inbox 条目。

## 跟踪项（显式）

- **跟踪载体**：本 pending 文件 + agent 记忆 `fenixd-maintree-stray-wip-refire` + 处置记录 `admin_disposition-admin-fenixd-1794854284.json`。
- **复查时机**：2026-11-18 daily self-review 窗口（读取 todo/knowledge）与下一轮 knowledge distill 消费本 pending 条目时做立项评估；若 2026-11-18 24:00 前未立项、而同形态第 9 度再告警，下一度 admin 处置 MUST 改为 `escalate=true` 转人工，并在 recommended_action 中点名本跟踪项失效。
- **绊线精确口径（2026-11-17 第 10 度处置消歧）**：`escalate=true` 的触发条件是「**同型告警发生于 2026-11-18 24:00（本地时区）之后**且届时仍未立项」——期限之前的同型再告警（含第 9/10 度）维持零触碰+跟踪项收口，不提前烧人工注意力；期限后首度同型告警 MUST escalate 并点名本跟踪项失效。

## 第 10 度再告警续记（2026-11-17 04:23Z，指纹 b2409791a7c421ad，16 文件）

- 同一活跃工作流延续并扩面：新增 core/evolution.py 与 core/dashboard/routes/evolution_routes.py（evolution 异步 accept / push 后台化改造，diff 注释自述「2026-11-16 批量同意超时事故引入」）及配套测试，叠加既有图标钮/窄宽度波/CLAUDE.md-SKILL.md 原型交付地址重构。
- mtime 波次：4 文件 2026-11-17 10:51:22 +0800 同秒批量重写、CLAUDE.md/SKILL.md 11:50 编辑——first_seen（11:53+0800）前仍在活跃编辑，活跃工作流实锤。
- 上轮在场 dsh web 会话本轮已退场 → 「归因出现→消失」转换再升级子形态第 3 次实证；两裁决选项断链/损伤反证均再证成立；track_stray_wip 提案仍未被注册表采纳（第 3 次回填 suggested_choice）。
- 绊线状态：未立项属实，但告警发生于期限前 → 本轮零触碰+跟踪项收口合规；escalate 武装至期限后首度同型告警。
