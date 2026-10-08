# design.md

## 上下文

- 事故：c91213f（2026-10-03）双删 .fenix/verify.yaml（33 行）与 .fenix/todo.md（86 行）并同提交引入 .gitignore 的 .fenix/* 整体忽略加两条 negation 例外；todo.md 次日被每日自省循环自愈，verify.yaml 无日常提交循环，脱落 6 天无人察觉。
- 机制缺口：/root/fenixd/core/worktree_manager/stray_wip.py 的未跟踪散件盘点对 negation 放行项显式豁免（:457-461 docstring、:505-506 `!` 开头不计入），admin_alerts.json 33 条 maintree_untracked_stray_stale 中 0 次提及 verify.yaml——豁免正确（白名单文件不是散件），但豁免之后没有任何机制反向核查白名单文件的 tracked 状态，形成零覆盖盲区。
- 白名单约定两处文档化零强制：.gitignore:16-18 注释、/root/fenixd/core/knowledge_audit.py:76（todo.md/verify.yaml/config.template.yaml 应入库）。

## 方案

### 1. 检测流（core/worktree_manager/stray_wip.py）

在 _untracked_stray_entries（:449-507）旁新增第三流：
- 复用既有 _git_check_ignore_detail 批量通道，跑 check-ignore -v -n --non-matching 拿到 negation 放行规则命中的路径；
- 对放行路径批量查 git ls-files，不在索引中的即为 whitelist_untracked 候选；
- `!` 放行 + untracked 即异常，无需新增 git 查询形态；豁免判据（放行不计散件）保持不变，两流互不污染。

### 2. 信号登记（core/admin_monitor.py）

- SIGNAL_SEVERITY（:359）与 SIGNAL_RECOMMENDATION（:451）两表登记新信号：severity major 接入唤起（对齐 maintree_untracked_stray_escalated 先例，不进 STORED_SIGNAL_TYPES 之外的第三态）；
- 文案写明「negation 放行即声明入库意图」，处置建议二选一：git add 恢复入库，或删除放行规则承认其为运行时文件。

### 3. 约定互引（core/knowledge_audit.py）

:75-77 注释补一句指向本巡检，使「白名单应入库」约定与执行机制互为引用，后来者可从任一侧找到另一侧。

### 4. 权衡与风险

- 不复用散件流改语义（那会破坏「白名单文件不是散件」的正确豁免），新增独立流是加法不是改法。
- check-ignore -n --non-matching 的输出需覆盖无任何规则命中的路径过滤（-n 会回显未命中项），实现按 rule 以 `!` 开头过滤。
- 测试沿用 tests/test_stray_untrack_remediation.py 的「不误伤/不漏报」双断言口径。
