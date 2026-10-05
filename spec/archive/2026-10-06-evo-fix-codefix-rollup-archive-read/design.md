# design — fix-codefix-rollup-archive-read

## 根因链

rollup 输入 _read_run_metrics（core/code_fix.py:471-497，路径构造 :479）只读顶层 .fenix/runs/<run_id>.jsonl；daemon 每 300 秒 runs retention 清理（fenixd.py:884-891 → core/dashboard/data/runs.py:1045 runs_retention_check）把终态 run 移入 .fenix/runs/archive/（该机制 09-21 上线）。code-fix 链横跨数小时，链终局时除末批外的 run 必然已移档 → turns 恒零。本窗口实测：fenixd.log:31407（runs=2 resolved=34 turns=0）、:31583（runs=1 resolved=19 turns=0）、fix-progress.json chain_rollup 全零。

## 修法

_read_run_metrics 改双路径回退：顶层 → .fenix/runs/archive/<run_id>.jsonl，对齐 core/admin_monitor.py:3401-3405 _admin_run_file 先例。回退顺序即取者优先级：retention 去重语义下顶层存在即最新副本，先读先赢。归零语义收窄为「两处皆缺」，fail-open 注释语义（归档缺失按零贡献、不炸链终局）保留。

## 回归样本

以本窗口两个真实零值 rollup 的形状为夹具：runs=2（对应 1790545294/1790546810，388+49=437 轮）与 runs=1（对应 1790576907，272 轮），修复后同形状输入应计得非零真实值。

## 边界

- 不做历史链追溯重算：rollup 依赖随链累积的 chain_run_ids、出账即清账，历史链不可再生；一次性归因用只读脚本（本窗口已实测 535/487 两批转录归因可行）。
- 不改触发时机（链末批合回/链中途终局）、清账语义、retention。

## Risks

- 顶层与归档副本并存：取顶层，结果一致性由单测覆盖。
- 读放大：每 run 至多一次额外 stat/open，量级可忽略。