# Design — 交付物声明修正：写回层与读取基准对齐

## Context

`declaration-relocation-protocol` 与 `deliverable-declaration-resolution` 已建立：
- 声明解析单一权威源 `resolve_effective_declaration`，优先序 **worktree 内文件 > 分支版本
  (`git show`) > 主树回退**，返回 `{deliverables, references, entries, source, spec_dir}`。
- 收工守卫 `_deliverable_gate_missing` 以该入口读取，逐条在**分支 HEAD** 校验 blob 存在。

但裁决侧（`core/pm_engine/dispatch/adjudication.py`）的机械修正（`typo` 改写 /
`reference` 软化 / 删除）写的是 `eff_spec_dir`，并经 `_commit_softened_declaration(spec_name, element)`
提交到 **`project_root`**（主树）。当守卫读取**未命中 worktree、回退到 worktree 前主树在
优先序之外**——实际事故态是「worktree 存在但与分支提交同样含旧声明」——修正落主树、
读取取分支/worktree，二者错层。

事故时序（add-code-review-auto-fix）：
1. `17:36` 实现 run 完成 → 守卫按分支版本解析 → 命中声明的笔误路径
   `pages/settings/components/CodeFixProgressCard.tsx`（kind: new）→ 分支 HEAD 无此 blob → `missing`。
2. `17:36` → `disputed` → blocked，派 dispute-judge。
3. `17:49` judge 判 `typo` → `replace_declared_path(eff_spec_dir=?)` + 提交主树
   （commit `25bc8da0`，仅主树 tasks.md L46 变为 `pages/projects/…`）。
4. `17:49`- 之后每轮：worktree/分支 tasks.md L46 **仍是 settings/…** → 守卫再读回旧路径 →
   再判 `missing` → 再打回重派 → 死循环。叠加 daemon 重启续做（每次 `recovery resume`
   重派），31 小时 / $44.98 仍 `implementing`。

关键佐证（本次调研取得）：
- 主树 L46 = `pages/projects/…`；分支 & worktree L46 = `pages/settings/…`；
  `git cat-file -e <branch>:pages/settings/…` 失败、`pages/projects/…` 成功。
- `_commit_softened_declaration` 注释自述「直接改写**主树** `spec/changes/<spec>/tasks.md`」，
  且 `engine._git_commit` 以 `cwd=project_root` 提交——写主树为既定行为。
- 分支上的「旧路径声明」随分支提交携带，恢复续做每轮都在该分支上重演 `missing`。

## Goals

- 「修正写入层」与「守卫读取层」同源：修正命中哪一层，就写哪一层。
- 无可行写入层时**不制造读不回来的修正**（改走打回 / 凭据通道）。
- 修正后以读取基准复检；不一致告警而非静默。
- 跨轮残留凭据可核销，脱出「重派但无从改」的死循环。
- 迁移期 TTL 熔断，上限后 blocked，兜住未覆盖形态。

## Decisions

### D1 修正写入落点 = 生效声明所在工作树（与读取基准同源）

判据：解析结果 `source == "worktree"` 且 `spec_dir` 指向 worktree 内 →
`replace_declared_path(spec_dir, …)` 就地写入并经**该 worktree 的分支**提交
（`_commit_softened_declaration` 增提交根参数，`engine._git_commit` 增 `cwd`/`repo_root`）。

理由：worktree 是「正在测的那份」的最高优先层；写它与守卫读取一致，修正立即可见。

### D2 无 worktree（source ∈ {branch, main}）时：不写主树就地生效

- `source == "branch"`（worktree 已清理，命中分支版本）：分支 HEAD 的声明由分支提交
  携带，必须由**实现方在分支内**改写 → 走既有缺件打回 / `relocate` 凭据通道；
  裁决侧 MUST NOT 以主树 `tasks.md` 为落点「就地改写」并视为生效。
- 迁移期（读取回退仅命中主树）时，若确无 worktree 也无分支（极罕见），主树就地改写
  **不优于**打回：因为本轮守卫必然已在分支/主树间有确定读取层。统一改走打回通道，
  避免「写主树、读分支」再次错层。

核心不变量：**修正被执行 ⇔ 下一次守卫读取能看到修正**。若不能，则视为修正未完成。

### D3 修正后复检熔断

修正确认后，以 `resolve_effective_declaration(spec_name, branch=…, worktree_path=…)`
复读，断言被修正的旧路径不再以原 kind 出现在 `deliverables`。不一致 → 记 error 明细
（含 source 与 spec_dir）并 `logger.warning`，MUST NOT 记成功。

### D4 跨轮残留凭据核销（脱困）

`_deliverable_gate_missing` 产出 `missing` 后，对每条命中 `_has_relocation_credential`
（已有实现，读 `.fenix/dispute_audits.jsonl`）且**替代路径在分支 HEAD 存在**的条目，
视为已核销（不加入违规清单）。此路径不依赖本轮 judge 是否再跑，故上一轮落册的凭据
在下一轮未 merge-back 时仍生效——正是事故态的解药。与 `removed` 收缩防护读同一审计流，
语义一致。防空洞核销：替代路径不存在则不核销。

### D5 复发熔断（迁移期兜底）

同一 spec 同一路径在 `typo` 修正后连续复发（守卫再判同路径 `missing`）计数，达到
`agents.max_retries` 上限 → blocked，error 明示「修正未生效于读取基准」。复用既有
`_redispatch_for_missing` 的 `_retry_count` / 封顶逻辑，仅将 error 文案区分该形态。

## Risks

- **回归面**：改动触及裁决流水线（judge 执行 + 守卫）。须 fail-safe：任何异常回退既有
  打回路径，不静默放行、不误 blocked。
- **写入 worktree 的并发**：实现 run 可能同时在 worktree 内跑（本轮即如此）。裁决写
  worktree 的 tasks.md 时须与实现 run 的 WIP 提交协调（写后立即提交，避免被 autostash/续做
  覆盖）；若 worktree 正被占用且写入冲突，降级为打回通道。
- **`_git_commit` 提交根扩展**：涉及 `engine._git_commit` 签名变更，须核对全部调用点
  （`_commit_softened_declaration`、删除/软化路径）不回归。
- **凭据核销误伤**：仅当替代路径真实存在于分支 HEAD 才核销，杜绝「凭据在册但交付物
  从未落地」的空洞放行。

## Migration

- 存量在飞 spec（含 add-code-review-auto-fix）在改动合入 daemon 后，残留凭据核销
  （D4）即可解除其死循环——无需重跑实现。
- 熔断（D5）为迁移期安全网，稳定后可保留（成本极低）。
