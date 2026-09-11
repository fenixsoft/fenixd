# add-impl-terminal-nocommit-gate 设计

## Context

2026-09-10 双 SPEC 首轮零提交全丢（合计 68.3min / $30.23 + 2 次 dispute-judge + 整轮重派）。死法链四层已逐层核实：

1. **触发源**：deepseek-v4-flash（inferaiapi）末轮输出格式回退——credibility a1 在 text 块内嵌完整 XML `<function_calls>`（内容恰为 `git add ... && git commit -m "[fenix] add-verdict-credibility-gate: Tasks 1-2 ..."`），wip a1 用 markdown 代码块写假 Edit。SDK 不从 text 解析工具 → `end_turn`「自然完成」（`terminal_reason=completed`，turns 120/126 ≪ 上限 600）。非被杀、非超时、非断流。
2. **成功判定不看提交**：`runner.py:2003` exit 0 + 合法结果文件 → success → `cleanup(success=True)`（runner.py:2308）；`git worktree remove` 遇 untracked 拒删 → `worktree_manager.py` fallback `shutil.rmtree` 静默硬删（仅一条 WARNING，fenixd.log 1028/1062 即毁灭现场铁证）。
3. **零变更哨豁免**：`_implementer_zero_change`（verification.py:2237）要求零提交**且**零 Edit/Write 才触发；两案有大量编辑调用 → 放行，其内「worktree 有 N 个未提交修改，重派务必 git commit」精准诊断路径从未到达。
4. **守卫时点在毁灭后**：交付物守卫（dispatch.py:748）校验基准为分支 HEAD blob，worktree 已 rmtree → 必然缺件 → 重派整轮重做（实测 32-36min/轮）。

零提交死法谱系：①排水杀在飞 run（add-interrupt-recovery-preserve 09-05 治理）、②shutdown 误判瞬断（fix-provider-transient-backoff + shutting_down 守卫 09-10 治理）、③本 SPEC 的「正常终态但零提交」。add-impl-wip-checkpoint（09-10 落地）锚点 A/B 只钉排水收口前与瞬断退避 sleep 前两处静默窗口，「run 正常终态」无锚点、无检测。wip 案死于自己要防的问题（dispute-judge 自注在案）。

关键既有设施（复用而非新建）：

- `AgentArtifactGateError` except 通道（runner.py:2032-2086，add-judge-artifact-gate 落地）：写 transient_retry + superseded 记录 → **调 `_wip_checkpoint_before_backoff`（锚点 B WIP 提交）** → `time.sleep(backoff)` → 同 worktree + `--resume` 续做；预算耗尽 error 自动加 `[provider-transient]` 前缀 → keep_for_reuse。
- `wt_dirty` 取证已在位：runner.py:2279-2288，成功路径 cleanup 前对 implementer/fast-track 执行 `git status --porcelain`，结果随 `AgentRunResult.worktree_dirty` 传递。
- `commit_wip_checkpoint`（core/wip_checkpoint.py:33）：幂等、尊重 gitignore、失败降级不阻断。

## Goals / Non-Goals

**Goals**

- implementer「正常终态 + 分支零提交 + worktree dirty」在 cleanup 前被拦截为可恢复错误，处置为 WIP 提交 + 原地退避 + resume 续做（分钟级），替代整轮重做（32-36min）。
- 机械归因透传（格式回退截断 vs 忘提交）供审计，不改变处置。
- cleanup rmtree fallback 前留 dirty 快照（纵深防御，覆盖终态门之外的所有车道）。

**Non-Goals**

- 不改零变更哨语义（真空转仍归它管）、不改交付物守卫时点与校验基准、不改 WIP 锚点 A/B。
- 不拦 fast-track / repair（成功不清理语义不变）与 verifier（产物由结果文件硬门管，dirty 不影响分支合并）。
- 不做 provider 侧修复（格式回退是 deepseek 网关模型行为，框架侧只能兜底）。
- 不实现「区分归因后差异化处置」（resume 对两种原因都正确，无差异化收益）。

## Decisions

### D1: 门 = 复用 `AgentArtifactGateError` 通道，而非新重试机制

终态零提交门在成功收口路径（runner.py `if success:` 分支、`wt_dirty` 取证之后、`cleanup` 之前）判定：`agent_type == "implementer"` 且 `rev-list --count main..branch` == 0 且 `wt_dirty` 非空 → `raise AgentArtifactGateError(error_text)`。

**为什么不用「stash 快照 + 直接重派」（原调查建议②）**：重派 = 整轮重做（实测 32-36min），且 stash 恢复到新 worktree 需要额外现场交接协议。复用通道后：锚点 B 先 WIP 提交（产物上分支）→ resume 续做（模型从「正要 commit」处继续，思考链、任务清单、会话上下文全保留）→ 分钟级收尾。预算耗尽时 keep_for_reuse 的保全语义与 stash 快照等效但已有机化（`_take_reusable_worktree` 认领）。

**为什么 error 文本不加 `[provider-transient]` 前缀**：except 通道已有判断「`if "[provider-transient]" not in error: error = f"[provider-transient] {error}"`」——`[terminal-no-commit]` 原文保留在前、通道自动补后缀，耗尽路径语义自动成立，零额外接线。但需注意：通道内 `record_transient_break` 会计入全局瞬断指纹——格式回退/忘提交不是网关问题，计入会污染 dispatch 闸门对瞬断风暴的可见性。**处置：门触发时不调 `record_transient_break`**（该调用在 except 块内由 `[provider-transient]` not in 前缀守卫，见下）。实现时若 except 块结构导致难以跳过，允许计入并在注释中声明误差方向（多计保守、少计危险）。

### D2: 判定顺序——先门后 cleanup，复用已取证的 wt_dirty

门插在 `wt_dirty` 取证（2279-2288）之后、`agent_type in ("fast-track", "repair")` 分流之前。`wt_dirty` 已在该点取证完毕，门零新增 git 调用（分支零提交检查的 `rev-list` 一次除外）。

分支零提交检查基准：`git rev-list --count main..{branch}`（与 `_implementer_zero_change` 同式，verification.py:2245）。branch 从 `worktree_manager.get_branch_name(wt_path)` 取（cleanup 前仍有效）。

### D3: 机械归因 = 末轮 text 特征匹配，非 LLM 判定

读 run 转录（`{sub_run_id}.jsonl`）最后一条含 text 块的 assistant 消息：text 含 `<function_calls>` 或 markdown fenced code 内出现 `Edit|Write|Bash|NotebookEdit` 调用形态（``` 后紧跟工具名/`<invoke`）→「格式回退截断」；否则「未提交即收工」。纯正则、零 LLM。归因写进 error 文案（`[terminal-no-commit] 归因:格式回退截断 ...` / `[terminal-no-commit] 归因:未提交即收工 ...`），不影响处置路径。

**备选否决**：LLM 归因（烧钱且慢，2 案 dispute 已证明机械四层足够）；不改归因直接重试（丢失「为什么成功却零提交」的审计线索，09-10 调查正是靠这条线索定位根因）。

### D4: rmtree 前留档用 `git stash create`（引用式，不入 stash 栈）

`cleanup` 的 rmtree fallback 前加：dirty 时 `git stash create "fenix: pre-rmtree snapshot <branch>"` → 记录返回的 commit SHA 到日志。选 `stash create` 而非 `stash push`：不污染 stash 栈（autostash 栈堆积 74 条的教训）、纯引用生成零副作用、`git stash store` 可随时转正。对全 agent_type 生效（verifier 的 09-09 untracked 告警同款暴露）。失败 WARNING 降级，不阻断。

**备选否决**：`git add -A + commit`（改变 worktree 状态语义，cleanup 语义应无副作用）；直接 rmtree 不留档（本案教训：毁灭后 dispute 只能靠转录间接取证）。

### D5: TDD 验证口径

- 门判定矩阵（tests/test_agent_runner.py 或新 test 文件）：零提交+dirty → 拦截且 error 带 `[terminal-no-commit]` 与归因；有提交 → 不拦；零提交+干净 → 不拦；fast-track/repair/verifier → 不拦；拦截后锚点 B WIP 提交发生、退避后续做用同 worktree。
- 归因正则（转录末轮假工具调用特征）：XML 形态 → 格式回退；markdown 代码块形态 → 格式回退；无特征 → 忘提交。
- cleanup 留档：rmtree fallback 触发时 stash create 被调用且 SHA 入日志；失败不阻断。
- 真实事故回归锚：用 1789001677 转录末轮 text（XML 假工具调用样本）做归因 fixture。

## Risks / Trade-offs

- **[门误伤合法零提交轮]** 实现者整轮只分析不写盘（合法）→ wt_dirty 空 → 不拦，天然安全；wt_dirty 非空但产物全为 gitignored → `git status --porcelain` 不含 ignored → 也不拦。残余风险极小。
- **[resume 续做后模型仍忘提交]** 第二次门触发 → 再次退避+resume；原地预算（transient_budget）耗尽后 keep_for_reuse 保现场，最坏退化为「下轮继承现场续做」仍优于整轮重做。
- **[record_transient_break 计入污染瞬断指纹]** 见 D1 处置：尽量跳过；否则注释声明「多计保守」误差方向。
- **[rev-list 对已删分支/异常 repo 失败]** 沿用 `_implementer_zero_change` 的失败即放行语义（returncode != 0 → 不拦），门 fail-open，绝不因门自身故障打断正常收口。
- **[wip 提交进 merge-back 历史]** 锚点 B 既有语义已覆盖：merge-back 前塌缩（collapse_wip_commits）把 `fenix(wip):` 前缀提交塌缩为单提交，主树历史无 wip 残留。

## Migration Plan

单仓库、纯框架侧、无配置新增（无 Dashboard UI 义务）。落地即生效（daemon 重启后新代码，注意 [[fenixd-daemon-stale-code]]：合并后必须重启 daemon）。回滚 = revert 单提交，门 fail-open 无持久状态。无迁移步骤。
