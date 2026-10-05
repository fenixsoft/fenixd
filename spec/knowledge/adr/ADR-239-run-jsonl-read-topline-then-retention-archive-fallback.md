# ADR-239：run 转录读取双路径回退，顶层优先归档兜底

date: 2026-10-06
status: accepted

## Context

daemon 每 300 秒 runs retention 清理把终态 run 转录移入 `.fenix/runs/archive/`，而 code-fix 消化链等长时段聚合常横跨数小时，链终局时除末批外的 run 转录通常已移档。凡只读顶层 `.fenix/runs/<run_id>.jsonl` 的消费者在长时段聚合上必然漏样本：链级 rollup 恒全零（turns=0）为实测根因。仓内同类缺陷已两度出现——admin_monitor 先行修复，code_fix 随后仍以单路径读取复发。

## Decision

凡消费 run 转录做聚合/对账的读取一律双路径回退：先读顶层 `.fenix/runs/<run_id>.jsonl`，缺失回退 retention 归档副本 `.fenix/runs/archive/<run_id>.jsonl`。回退顺序即取者优先级：retention 去重语义下顶层存在即最新副本，两处并存取顶层。缺失语义按「顶层与归档两处皆缺」判定；读不到按零贡献 fail-open，MUST NOT 中断调用方主流程（如链终局出账）。

## Consequences

单路径只读顶层的新增消费者被此裁定排除；每个 run 至多多一次 stat/open，读放大量级可忽略。不做历史链追溯重算——rollup 出账即清账、历史链不可再生，一次性归因走只读脚本不入框架。
