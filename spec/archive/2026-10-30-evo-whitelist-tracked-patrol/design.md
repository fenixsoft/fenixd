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
- 去重沿用 untracked 流同款指纹注册表口径（``_untracked_registry`` + 指纹消失自动复位，stray_wip.py:202、:695-699），指纹取放行-未跟踪路径排序集 + 逐文件内容 sha256（untracked 不可复用 tracked 指纹形态，同 :725-726 口径），同集合只发一次。

### 2. 信号登记（core/admin_monitor.py）

- **三表登记**（对齐 maintree_untracked_stray_escalated 先例，stray_wip.py:775-777 明文「三表登记接入自动唤起」）：SIGNAL_SEVERITY（表头 :290，先例项 :364）登记 severity major；SIGNAL_RECOMMENDATION（表头 :397，先例项 :456）登记文案与处置建议；**并收录 STORED_SIGNAL_TYPES（表头 :493，先例项 :556）**——两表不够：摄取循环只对收录类型无条件唤起（admin_monitor.py:354 注释、:500-502），未收录则记录落 store 后无人摄取、信号石沉大海（verify_uniform_failure 事故先例 :537-544）；
- 发信号时 evidence 须含「项目名=」段（无 spec 形态摄取解析单源，对齐 _write_untracked_escalated_alert :779-781 同款）与「文件清单(N):」段；
- 文案写明「negation 放行即声明入库意图」，处置建议二选一：git add 恢复入库，或删除放行规则承认其为运行时文件。

### 3. 约定互引（core/knowledge_audit.py）

:75-77 注释补一句指向本巡检，使「白名单应入库」约定与执行机制互为引用，后来者可从任一侧找到另一侧。

### 4. 权衡与风险

- 不复用散件流改语义（那会破坏「白名单文件不是散件」的正确豁免），新增独立流是加法不是改法。
- check-ignore -n --non-matching 的输出需覆盖无任何规则命中的路径过滤（-n 会回显未命中项），实现按 rule 以 `!` 开头过滤。
- 测试沿用 tests/test_stray_untrack_remediation.py 的「不误伤/不漏报」双断言口径。
