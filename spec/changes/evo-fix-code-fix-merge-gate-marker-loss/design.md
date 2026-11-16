# 设计：code-fix 合并门纯标记提交保全

## Context

合并门零有效修复守卫（core/code_fix.py `if not fixed_ids or commits <= 0:`，2026-11-16 实测 :7923）以 fixed=0 一票拒合回，ignored 计数只进拒合回 warning 文案（:7942）不参与判定；全批 ignored 且 pending 为空时走「批按完成收尾」（「无需合回」分支，2026-11-16 实测 :7924-7934，`_safe_cleanup(success=True)`）同样不合回——纯标记提交在守卫任何分支上都无合回通道。弃件仅 warning 日志（无 commit id、无告警），run 终态在 runner 层（core/agent_runner/runner.py:10640）于合并裁决前发出。fenix-ignore 标记读写契约已存在：写侧 agents/code-fix.md「忽略标记」节，读侧审查注入 core/agent_runner/maintenance_runs.py:4832-4838（`OCR_IGNORE_MARKER_BACKGROUND`）——源文件删除后指纹去重失效，标记是唯一跨轮误报抑制。弃件史：全日志 14 起拒合回，弃掉提交（commits>0 被拒）在档可考至少 4 起（10-14 16:22Z commits=1 一起内容未考、10-19 一起内容不明已永久不可考、11-14 两起纯标记）。

## Goals / Non-Goals

- **Goals**：纯标记提交不再被合并门任何分支丢弃；弃件必留可捞回凭证（完整 SHA）；批级产物去向可对账，三层认知（fixer 自述/run 终态/合并门结果）一致。
- **Non-Goals**：不改 runner 层 run_metrics 发出时点与语义（结构性时序：发出时合并结果尚未产生）；不建内容级可修性判断（放行判据仅「形态=纯标记注释」）；不动 commits=0 零产物批的既有拒合回；不在本 SPEC 内执行存量两弃件的主树捞回（人工步骤）。

## Decisions

**D1 放行判据=形态核查，不做语义判断。** 提交 diff 新增行全部为含 `[fenix-ignore:<item_id>]` 标记本体的注释行、且删除行仅为标记注释行或为空才放行——删除行约束防「删实质代码+贴标记」形态穿透核查；注释语法不枚举定死，按文件语言形态匹配（写侧契约 agents/code-fix.md「忽略标记」节明示 Python/YAML 用 `#`、TS/JS 用 `//`；11-14 实例 00162a0 为 TS 文件内 `<!-- -->` 形态，可含尾随说明文字）。混合批不放行但必留痕 commit id+非标记文件清单。理由：needs_human 条目 83cd96365323 实证 fixed=0 批里可能藏真修复（后被真修 resolved 1/1）——可修性判断超出门禁职责，形态判据保守且机械可测。

**D2 两分支同治。** 拒合回分支（2026-11-16 实测 :7935-7952）与全批 ignored 完成收尾分支（:7924-7934）共用同一「纯标记核查→合回」前置段，堵住「换条路照样丢」；放行批的 pending（非 ignored）条目比照拒合回分支入 chain_skipped（保留下链重试语义，不核销不置终态——needs_human 类条目保留既有重试/止损路径）。

**D3 留痕=admin store 告警，先于清理。** 拒合回时落告警（完整 SHA、条目 id、非标记清单），顺序先落留痕再 _safe_cleanup——worktree 清理后分支即删，留痕是唯一捞回凭证（10-19 反例实证）。

**D4 产物去向挂链 rollup 与台账注记，不动 run_metrics。** 改 runner 记录时点会牵动全部车道终态语义；批级对账面（rollup 行 + 台账注记「产物已合并/产物已弃（commit <sha>）」）足够消除三层矛盾。

**D5 合回复用既有批合回通道。** 放行合回与 fixed>0 批同路径（含既有冲突 salvage 流程），不新写合并逻辑；纯标记批不含源码语义变更，跳过回归与既有差异一致，rollup 注记「纯标记合回」供审计。

## Risks

- 标记形态误判（含标记的混合提交被当纯标记放行）：判据限定「全部新增行均为注释形态」+ 测试钉死混合批反例（2.2）。
- 放行批无回归验证的审计疑问：纯标记注释不触运行时行为，与 fixed>0 批跳过场景的既有口径一致，rollup 注记留审计锚。