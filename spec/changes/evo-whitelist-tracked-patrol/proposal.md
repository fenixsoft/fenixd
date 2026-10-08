# whitelist-tracked-patrol

## 背景

potplayer-base 的验证契约 .fenix/verify.yaml 自 10-03 起被提交 c91213f 从 git 索引误删 6 天未察觉：同提交既新增 .gitignore 的 !.fenix/verify.yaml 例外（白名单约定「状态文件随仓库入库」）又删除了该文件，盘上未跟踪副本与被删版逐字节一致从而掩盖问题。6 天未察觉的机制性根因经回源核实为：框架对 negation 放行文件显式豁免散件盘点（/root/fenixd/core/worktree_manager/stray_wip.py:457-461 恰以 !.fenix/verify.yaml 为实测样本），豁免之后无任何机制核查「白名单文件是否真的 tracked」——白名单约定两处文档化（.gitignore 注释、core/knowledge_audit.py:76）却零强制，脱落只能等 fresh clone 或新开 worktree 断链才暴露。

反常不变量很干净：被 `!` 规则放行（= 声明了入库意图）却处于 untracked 态的文件，几乎必然是脱落事故。

## 目标

1. 主树未跟踪盘点旁新增独立检测流：命中 `!` 放行规则但不在 git 索引中的路径，发独立信号（negation-放行-未跟踪）。
2. 新信号接入唤起（severity major，对齐 maintree_untracked_stray_escalated 先例），文案写明「negation 放行即声明入库意图，放行+未跟踪＝白名单脱落」。
3. 白名单约定与执行机制互引（knowledge_audit.py 注释补指向）。
4. 一次性处置：potplayer-base 恢复 .fenix/verify.yaml 入库。

## 非目标

- 不改变既有散件流（maintree_untracked_stray_stale）与升级流（maintree_untracked_stray_escalated）的语义与豁免规则。
- 不自动执行 git add 类修复动作，信号只唤起人工/裁决处置。
