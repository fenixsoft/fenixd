# code-fix 合并门纯标记提交放行与弃件留证

<!-- knowledge: capability=code-fix-merge-gate rev=1
     sources=spec/archive/2026-11-27-evo-fix-code-fix-merge-gate-marker-loss -->

code-fix 车道合并门对 fixed=0 批的放行与弃件处置：fenix-ignore 误报标记提交有合法合回通道，被弃产物必留可捞回凭证，批级产物去向可对账。源内标记是防同一误报下轮复发重烧修复轮的唯一跨轮抑制手段（审查侧「就近有标记 MUST NOT 再上报」的注入约定全靠标记进 main 兑现）。

## 规则

### 纯标记提交放行

- 合并门零有效修复守卫（fixed=0 或 commits=0 即拒合回）对 fixed=0 且 commits>0 的批先做形态核查再裁决。纯标记批判据：批内全部提交的新增行均为含 `[fenix-ignore:<item_id>]` 标记本体的注释行，删除行仅为标记注释行或空行，且批内至少出现过一行标记本体（防空提交/纯元信息提交搭放行通道）；满足即合回该批提交并按批完成收尾（consumed，链继续）。
- 放行判据是机械形态核查，不做内容级可修性语义判断。注释语法不按文件扩展名绑定，按已知注释形态并集识别（`#`、`//`、`/*`…`*/`、`<!--`…`-->`、`--`、`;`，可含尾随说明文字；块注释形态须同行闭合）；不在并集内的形态保守按非标记处理。
- 穿透与 fail-closed 边界：删除行含任一非标记内容行即判混合批（防「删实质代码 + 贴标记」）；二进制文件内容保守按非标记计；git 判据不可得（diff 解析失败/提交数为空）保守按混合批拒放。混合批 SHALL NOT 放行。
- 放行合回复用既有批合回通道（merge-back 预演闸 / WIP 预检 / 冲突 salvage 流程全保留，不新写合并逻辑）；纯标记注释不触运行时行为，跳过回归与 fixed>0 批的既有跳过口径一致。fixed_ids 为空无核销集合，不置任何条目 `resolved`。
- 放行批内 pending（非 ignored）条目比照拒合回分支口径入 `chain_skipped`：保留下链重试语义，不因批放行而核销或置终态（needs_human 类条目的重试/止损路径保留）。
- 放行批合回命中主树 WIP 阻断走既有 defer 零预算延迟合回路径（fixed_ids 为空，无白洗条目问题）；真冲突时弃件留痕先于清理、按拒合回收尾链继续，reason=`marker_only_merge_back_conflict`。

### 全批 ignored 收尾分支同治

- fixed=0 且全批 ignored 的「批按完成收尾」分支（条目全部置 ignored、pending 为空）在收尾前执行同一纯标记核查：纯标记批先合回再按完成收尾，MUST NOT 以 success 终态静默丢弃；混合批/判据不可得的残余产物同样先留痕再收尾，不零留痕丢弃。

### 拒合回弃件强制留痕

- 合并门发生拒合回（commits>0）时落一条 AdminStore kind=SIGNAL 告警（signal_type=`code_fix_batch_discarded`，severity=warning），内容含全部被弃提交的完整 SHA、对应批条目 id、非标记文件清单、批号与分支；git 判据不可得时至少留 worktree tip SHA 兜底，不静默弃件。
- 留痕 MUST 先于 worktree 清理——清理后分支即删，告警是人工按 SHA cherry-pick 捞回的唯一凭证。
- 被弃 SHA 同步并账进链级进度快照（随链累积去重，链终局随 rollup 出账）；并账写盘 fail-open，不阻断批收尾。commits=0 零产物批无被弃产物，维持既有 warning 口径不告警。

### 产物去向进批级终态

- 链收尾 rollup 与台账注记区分「产物已合并（纯标记）」（纯标记合回批次计数 `chain_marker_merged`）与「产物已弃（commit <sha>）」（被弃 SHA 清单 `chain_marker_discarded`），消除 fixer 自述 / run 终态 / 合并门结果三层认知矛盾。
- run 层终态（run_metrics）发出时点与语义保持不变：发出时合并结果尚未产生，批级对账由链 rollup 与台账注记承担，不改 runner 层记录时点。

## 代码锚点

- 形态核查判据原子与批级核查：`core/code_fix.py`（`_MARKER_BODY_RE` / `_is_marker_comment_line` / `_commit_marker_review` / `_batch_marker_review`）
- 纯标记放行合回与弃件留痕：`core/code_fix.py`（`_merge_marker_only_batch` / `_trace_discarded_artifacts` / `_chain_note_discarded` / `_write_discarded_batch_alert`）与批收尾守卫前置段、`_chain_rollup_snapshot`
- 标记写侧契约：`agents/code-fix.md`「忽略标记」节；审查侧注入消费方：`core/agent_runner/maintenance_runs.py`
- 守卫测试：`tests/test_code_fix_marker_only_merge.py`

## 溯源

- 2026-11-16 evo-fix-code-fix-merge-gate-marker-loss（spec/archive/2026-11-27-evo-fix-code-fix-merge-gate-marker-loss/） — 新建本页：合并门纯标记提交放行（形态核查判据、全批 ignored 收尾分支同治）、拒合回弃件强制留证（AdminStore 告警含完整 SHA、留痕先于清理）、产物去向进链 rollup 与台账注记（不动 run_metrics 终态语义）。
