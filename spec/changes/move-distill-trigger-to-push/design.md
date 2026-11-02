# Design: move-distill-trigger-to-push

## Context

知识蒸馏触发链（add-knowledge-atlas 建立）：归档移动成功 → `commit_archive_move`（core/archive_commit.py:38 单点漏斗，三路归档汇聚：CLI `bin/fenix_archive.py` / dashboard `spec_archive.py` / daemon `auto_archive_check`）→ `dispatch_distill` → 门控链（enabled → 归档目录存在 → 回填期排队）→ `DistillManager` 批 run。

问题：归档滞后交付。R1 阈值排水（终态积压 ≥50）与 R2/R3 时效归档（终态+报告+滞留 ≥72h）才是日常归档主力，SPEC 从 pushed 到知识页产出平均延迟 3 天+。

pushed 写点侦察结论：`PmEngine.approve_push`（core/pm_engine/engine.py:3248 附近）是 done→pushed 的**单点写点**——人工 fenix-approve 与 `_auto_approve`（approve_mode=auto 自动档）双路汇聚；函数内自带完整幂等守卫（已 pushed 幂等 skip / 非 done 拒绝 / push 退避期跳过 / 全临界区持锁 check-then-act）。这是与 `commit_archive_move` 同构的单点漏斗。

语义安全性：pushed 是终态（`TERMINAL_SPEC_STATUSES = ("done", "pushed")`），push 后 SPEC 内容不再变化——蒸馏读 `spec/changes/<名>` 即读到最终版。

## Goals / Non-Goals

**Goals**

- push（done→pushed 转移）即蒸馏，知识页产出紧跟交付节奏
- 归档不再触发（无双触发）；归档时补做「溯源链接迁移」，保持知识页链接任何时刻指向真实路径
- 全链 fail-open 口径与归档触发时代一致

**Non-Goals**

- 不动蒸馏执行面：`DistillManager` 批结构、队列合并、修正轮、flock 单飞、run 产物写侧（add-distill-run-artifacts）、回填期排队门——全部原样
- 不做 done-未-push SPEC 的兜底蒸馏（语义收窄是本变更的目的：push=交付确认）
- 不迁移存量知识页的历史归档链接（它们指向的归档目录真实存在，契约仍自洽）
- 不动 approve_push 的退避/幂等/持锁语义（只在其成功转移后追加派发点）

## Decisions

### D1：派发挂载在 approve_push 成功转移后（而非状态机通用转移钩子）

`approve_push` 是唯一合法的 done→pushed 写点（其他路径写 pushed 的只有残痕回填 `backfill_push_residuals`——它只清 error 不改 status，不触发）。挂载点选在「状态转移成功之后、函数返回之前」，`distill=` 参数注入替身（测试隔离，仿 archive_commit 的 `distill=` 既有模式）。

- 备选（否决）：状态机 update_spec 通用钩子——转移写点分散（dashboard 修改状态弹窗/CLI 等多路 update_spec 直写，memory：打回路径全部 update_spec 直写），通用钩子要么误触发非 push 转移要么需要 per-status 白名单，复杂度更高且错过语义锚点；approve_push 单点已覆盖人工+自动双路。
- 派发参数：单 SPEC 名（approve_push 一次推一个）。`dispatch_distill` 既有批量入口保留（恢复重派/未来批量场景用）。

### D2：蒸馏源目录概念替代归档目录（内部参数化，双态探测）

`dispatch_distill(archived_name)` 语义改为「蒸馏源名」。三处消费点统一双态解析（changes/ 优先、archive/ 兜底）：

1. `_gate_distill` 存在性检查：`(changes/<n>).is_dir() or (archive/<n>).is_dir()`，双缺拒绝（reason 保留 `archive-dir-missing` 字面量兼容既有消费方，文案补双态说明）；
2. `build_distill_prompt`：动态段按双态探测结果给真实绝对路径；
3. `recover_pending`：恢复重派走同一门控链（既有路径），双态解析自动覆盖。

内部形参名 `archived_names` 是否改名：**不改**（跨 dispatch/mgr/worker/测试替身的签名面大，语义标注放 docstring；改名收益纯美学，风险面实在）。唯一必改是 prompt 动态段「本次待蒸馏的归档」→「本次待蒸馏的 SPEC」及 distill.md 模板语境。

### D3：溯源契约 = 蒸馏写 changes/ 链接 + 归档改写 pass（而非读侧动态解析）

蒸馏时刻 SPEC 恒在 `spec/changes/<名>`，模板溯源契约改为链接指向 changes/ 路径。归档移动后链接会断——在归档移动成功后的单点加改写 pass：`spec/knowledge/` 全页扫描该 SPEC 名的 `spec/changes/<名>` 字样（链接与 sources 行）→ 替换为 `spec/archive/<date-name>`，git add 并入归档提交。

- 备选 A（否决）：知识页记裸 SPEC 名、dashboard/audit 读侧动态解析位置——契约级改动扩散到 dashboard 弹窗、`_check_links`、knowledge_audit 检查器与全部存量知识页（memory：审计链接门是本仓已知痛点，读侧契约变更风险最大）。
- 备选 B（否决）：归档后重蒸馏一次（让 agent 自己改链接）——一次蒸馏 = 一次 claude -p + 修正轮，纯路径替换用 agent 是浪费且引入新的失败面。
- 改写点覆盖义务：归档移动的物理单点在双路径（`bin/fenix_archive.py` 与 `core/dashboard/data/spec_archive.py` 的 archive_spec）各自移动成功后——与 `commit_archive_move` 时代「双路径共同漏斗」同构，改写器做成单函数（core/knowledge.py 或独立小模块）双路径调用，禁止复制粘贴两份实现。
- 改写并提交的方式：复用归档提交流程——移动 + 知识页改写同批 `git add`（`spec/archive/` 删除侧 + 新增侧 + `spec/knowledge/`），单一 `[fenix] archive:` 提交。改写器在 git add 之前完成文件替换即可；异常 fail-open（告警留痕，归档照常——此时知识页出现死链，由 knowledge audit 链接门在下一轮审计兜底暴露）。
- ** sources 行的日期前缀**：归档目录名带日期前缀（`2026-11-02-<name>`），改写按「changes 名 → 当次实际归档目录名」映射精确替换，不做模糊 glob。

### D4：校验/审计两态兼容（核对义务）

- `validate_knowledge._check_links`（knowledge.py:287）：剔除代码块后逐链接「可解析 + 不越出真相源目录」——`spec/changes/<名>/` 与 `spec/archive/<名>/` 同为仓库根相对路径，机制上两态等价；任务中以用例锁定（changes 态链接不报违规）。
- `core/knowledge_audit.py`：溯源检查若存在 `spec/archive/` 前缀锚定（模板时代的 sources 契约），需放宽为「链接目标目录存在」——**实现前先 grep 该文件对 ARCHIVE_DIR 的引用，逐点核对**（防修复引入新误报，memory：模板段位误报家族）。
- distill.md 模板改动面：开篇语境（「刚归档进 spec/archive/」→「刚 push 完成进入终态，稍后将归档」）、sources 行格式（`spec/changes/<名>`）、溯源链接格式与「只给真实存在的目录加链接」守则（changes/ 语境）。模板是蒸馏 agent 的唯一契约载体，改写须与 `_check_links`/audit 的实际检查逻辑互相对照（勿引入第三种形态——memory：全角括号引用形态事故）。

### D5：语义边界全集

| 场景 | 行为 |
|---|---|
| done→pushed 成功 | 派发蒸馏（SPEC 在 changes/） |
| pushed 幂等回放 | 不派发（approve_push 既有守卫） |
| 非 done / 退避期 / SPEC 不存在 | 不派发 |
| pushed→打回→重新 done→pushed | **重新派发**（SPEC 内容可能已变，重蒸馏=知识页更新，语义正确；approve_push 的 done→pushed 转移天然支持） |
| pushed 后 3 天内蒸馏失败 | pending 台账保留，daemon 重启恢复重派（双态探测兜底） |
| 归档移动 | 改写 pass（不再蒸馏） |
| done 永不 push | 永不蒸馏（声明收窄） |

## Risks / Trade-offs

- **[改写 pass 缺位/失败 → 归档后知识页死链 → audit 链接门误伤蒸馏轮]** → fail-open 告警留痕 + audit 兜底暴露；改写器单函数双路径调用（禁复制粘贴）；任务含端到端用例（push 蒸馏→归档→改写→校验全绿）。
- **[distill.md 模板改写引入第三种链接形态 → agent 产出违规 → 修正轮耗尽 give_up]** → 模板改动必须对照 `_check_links` 的正则与 audit 检查器实际逻辑（任务含模板↔检查器一致性用例）。
- **[approve_push 高频路径新增派发开销]** → dispatch_distill 是入队+台账写（毫秒级）+ fail-open；蒸馏重活全在后台 worker。
- **[恢复重派双态探测在 changes/ 存在但内容已变（打回重做中）]** → 恢复重派读到的可能是新版 SPEC——蒸馏内容略滞后于打回，但 pending 批本来就是旧版交付的蒸馏任务，知识页幂等更新语义下可接受；重 push 时会再触发新蒸馏覆盖。
- **[归档提交混入知识页改动改变 `[fenix] archive:` 提交形态]** → 既有消费方（git log grep 归档、回填台账）按 subject/目录匹配，不受文件清单变化影响；提交 subject 不变。

## Migration Plan

纯行为迁移，无数据迁移：新触发只对新 push 生效；存量 pushed SPEC（29 个终态）不会被补蒸馏（等时效归档时走改写 pass=无改写对象，自然收敛）；回滚 = revert approve_push 挂载 + 归档挂载还原（改写器留置无害——归档触发时代知识页链接本就写 archive/ 路径）。

## Open Questions

无——写点、双态解析、契约衔接、语义边界均已在侦察中定案。
