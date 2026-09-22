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

### D1 修正写入落点 = 守卫实际读到的那一层（同源），提交根随落点

判据（`resolve_writeback_target`）= **写入层是否等于守卫实际读到的那一层**：

- `source == "worktree"` → 落点 `spec_dir`（worktree 内 spec 目录），执行
  `replace_declared_path(spec_dir, …)` 就地写入并经**该 worktree 的分支**提交
  （`_commit_softened_declaration` 增提交根参数，`engine._git_commit` 增 `cwd`/`repo_root`）。
  理由：worktree 是「正在测的那份」的最高优先层；写它与守卫读取一致，修正立即可见。
- `source == "main"` → 落点 `spec_dir`（**主树** spec 目录），提交根 `project_root`。
  理由：`source == "main"` 意味着 worktree 与分支版本均未命中声明段，**守卫本轮也是
  读主树**——就地写主树即同源，不存在错层；此处禁止写主树反而会误伤既有可用路径
  （`_preclassify_missing` / reference 软化的主树就地软化 + 立即提交，是 2026-09-15
  merge-back 死锁修复的前提，见 `tests/test_deliverable_declaration_triage.py:912-967`）。
- `source == "branch"`（`spec_dir is None`）→ **不可写**（D2）。
- `source is None` → 不可写。

### D2 仅 `source == "branch"` 时：不写主树「就地生效」

`source == "branch"` 表示生效声明只存在于分支对象库（worktree 已清理，`git show`
命中），**无落盘位置**（`spec_dir is None`）。此时裁决侧 MUST NOT 以主树 `tasks.md`
为落点改写并视为生效——事故正是「写主树、守卫读分支」：`adjudication.py` 现把
`eff_spec_dir = spec_dir or 主树` 回退后直接 `replace_declared_path`，
`_commit_softened_declaration` 又以 `cwd=project_root` 提交（commit `25bc8da0`：仅主树
tasks.md 变更）；分支 HEAD 的声明必须由**实现方在分支内**改写 → 走既有缺件打回 /
凭据通道，并保证该条裁决（typo 的 element + actual_path）落 dispute 审计流，供 D4 在
下一轮核销。

核心不变量：**修正被执行 ⇔ 下一次守卫读取能看到修正**。若不能，则视为修正未完成。

### D3 修正后复检熔断

修正确认后，以 `resolve_effective_declaration(spec_name, branch=…, worktree_path=…)`
复读，断言被修正的旧路径不再以原 kind 出现在 `deliverables`。不一致 → 记 error 明细
（含 source 与 spec_dir）并 `logger.warning`，MUST NOT 记成功。

### D4 跨轮残留凭据核销（脱困）

`_deliverable_gate_missing` 产出 `violations` 后，**仅对 `violation == "missing"` 的
条目**判定核销（`undeleted` / `removed` 仍走既有通道）：命中凭据且**替代路径在分支 HEAD
存在**的条目视为已核销（不加入违规清单）。此路径不依赖本轮 judge 是否再跑，故上一轮
落册的凭据在下一轮未 merge-back 时仍生效——正是事故态的解药。与 `removed` 收缩防护读
同一审计流，语义一致。防空洞核销：替代路径不存在则不核销。

实现要点：既有 `_has_relocation_credential`（`core/deliverables.py:767`）是**布尔**判定，
不返回替代路径，「替代路径在分支 HEAD 存在」的前置校验无据可依 → MUST 同源新增一个
返回替代路径的查询辅助（`new_path` / `actual_path`）。

### D5 复发熔断（迁移期兜底）

同一 spec 同一路径在 `typo` 修正后连续复发（守卫再判同路径 `missing`）计数，达到阈值
→ blocked，error 明示「修正未生效于读取基准」。**计数 MUST 用独立字段**
（如 `_writeback_recur_streak`），MUST NOT 复用 `_retry_count`：后者在恢复续做
（`state_machine.py:1729` `_recovery_resume` 分支）与重建分支（`:1469`）被显式清零，而
`resolve_env_blocked_reset_path`（`branch_guard.py:23-53`）会把本类 loop 的 blocked 复位为
ready 续走重实现，故既有封顶（`adjudication.py:1675-1681`）在本形态中形同不存在——事故
态实证：31 小时在飞期间 `.fenix/STATE.md` 的 `_retry_count` 恒为 `0`。独立字段 MUST NOT
随 blocked→ready / 恢复续做清零，仅在修正复检通过或退出本形态时清零。

## Risks

- **回归面**：改动触及裁决流水线（judge 执行 + 守卫）。须 fail-safe：任何异常回退既有
  打回路径，不静默放行、不误 blocked。
- **写入点遗漏（同一错层的其它落点）**：`tasks.md` 声明段的写入点不止 judge 执行三处——
  `adjudication.py::_preclassify_missing`（`:358-367` 取值回退 + `:416-420` 写盘软化）与
  `adjudication.py::_preclassify_orphan`（`:553-560` + `:616` 删除条目）同样以
  `spec_dir or 主树` 回退后写盘，属同一「写主树、读分支」错层；漏接线则本 SPEC 目标
  仅部分达成（tasks 2.5 要求全量清点并逐一接线）。
- **既有断言回归（main 来源就地写入语义）**：`source == "main"` 的就地写入 + 立即提交
  是 2026-09-15 merge-back 死锁修复的既有行为，被
  `tests/test_deliverable_declaration_triage.py::TestSoftenedDeclarationIsCommitted`
  锁定（fixture 无真实 worktree/分支 → 解析为 main）。D1 的判据 MUST NOT 把 main 来源
  一刀切为不可写，否则该路径回归（tasks 6.2 已列核对项）。
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
