<!-- knowledge: capability=cli-status-panel rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 框架状态面板报告

`skills/fenix-status` 与 `bin/fenix_status.py` 产出框架整体状态报告，是 `/fenix-status` 的数据源。

## 现行规则

- 面板数据与 Dashboard 共用 `core/dashboard/data.py` 数据层，脚本只做机械拼装事实数据。
- 裁剪契约：活跃 SPEC 逐行列出；`done`/`pushed` 终态折叠为统计行，名字不外显。
- 信号汇总段是供 LLM 分诊的原始问题素材，每行自带严重度前缀（🔴/⚠️/ℹ️）。
- 已知等待（冻结、定时拾取）单列展示，明确不算问题，不进入告警口径。
- 「需要关注」分诊由执行 skill 的 LLM 依据信号汇总段现场判断，脚本不给结论。
- 禁止 echo 输出 ASCII 装饰横幅；开头一句话概括整体状态。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
