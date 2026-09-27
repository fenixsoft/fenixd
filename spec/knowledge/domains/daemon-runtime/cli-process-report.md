<!-- knowledge: capability=cli-process-report rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# SPEC 进度 CLI 报告

`bin/fenix_process.py` 产出单个 SPEC 的详情报告，是 `/fenix-process` 的数据源。

## 现行规则

- 用法：`python3 fenix_process.py <spec-name>`，输出面向 LLM 分诊的 TUI 报告。
- 主数据源与 Dashboard 同源：共用 `core/dashboard/data.py` 的 `spec_detail()`（即 `/api/specs/<name>` 同一份组装），禁止另写一套读取口径。
- 额外补充 `spec_summary` 的预算三字段与 worktree 检查结果。
- 脚本只做机械拼装事实数据；「需要关注」分诊由执行 skill 的 LLM 依据报告内容现场判断，脚本不给结论。
- 报告字段以 Dashboard API 同形为契约，两侧数据不一致视为读侧缺陷。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
