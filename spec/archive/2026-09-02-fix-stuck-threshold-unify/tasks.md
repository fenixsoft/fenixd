# Tasks: fix-stuck-threshold-unify

## 1. 派生助手与接入（design D1/D2/D4）

- [x] 1.1 config.py 新增 `effective_stuck_threshold_seconds(config)`：`run_timeout_seconds + 600` 常量宽限；run_timeout 缺失或 ≤0 时回退 4200 并打 WARNING；补单测（9000→9600 / 缺省回退 / 显式旧值不影响结果）
- [x] 1.2 pm_engine.check_blockers（原 L1750 stuck_threshold_minutes 读取点）与 admin_monitor（get_admin_config 回退链原 L306-312）改调助手并删除旧键读取逻辑；补单测（两处消费点均取派生值）
- [x] 1.3 旧键（schedule.stuck_threshold_minutes / admin.stuck_threshold_minutes）存在时打一次性 WARNING（模块级生命周期去重）；补单测（首次告警 / 二次静默）

## 2. absolute_max 联动护栏（design 补充）

- [x] 2.1 timeout_supervision.absolute_max_seconds 校验：配置值 < run_timeout_seconds + extension 总上限时打 ERROR 并按 run_timeout_seconds + 7200 兜底生效；config.yaml 默认值对齐 14400；补单测（7200 vs 9000 的纠正用例 / 合法值不干预）

## 3. 配置清理与回归

- [x] 3.1 config.yaml 移除 schedule.stuck_threshold_minutes 行，留注释说明派生关系（run_timeout + 600）
- [x] 3.2 全量 pytest 通过（重点 tests/test_core.py、config 相关及新增用例），对照 capability spec 全部 Scenario 逐条核对覆盖并记录结论
