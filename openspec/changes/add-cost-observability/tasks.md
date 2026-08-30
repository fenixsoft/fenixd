# Tasks: add-cost-observability

实现依据（实施 agent 必读）：
- 能力定义 `specs/cost-observability/spec.md`；设计决策 design.md D1-D5
- 采集点：`.fenix/core/agent_runner.py` run 收工处（result.usage）
- STATE 内部字段写回：`.fenix/core/state_machine.py`（`_` 前缀机制，add-inplace-bug-repair 已落地）
- Dashboard：`.fenix/core/dashboard/data.py` SPEC 详情管道 + config 页（新配置键必须带界面）
- 合成器：`.fenix/core/verify_report.py`
- 真实夹具：`.fenix/runs/impl-v2-config-page-*.jsonl`（usage 结构样本）

## 1. 采集与累计

- [x] 1.1 agent_runner 收工处统一提取 usage（input/cache_creation/cache_read/output），累加 `_tokens_in`/`_tokens_out` 写 STATE（异常 run 按 0 + DEBUG 日志）
- [x] 1.2 验证链侧车 `.fenix/verify-progress/<spec>/tokens.json`：planner/judge run 用量逐轮记录

## 2. 展示

- [x] 2.1 Dashboard SPEC 详情治理区展示「输入 42.0M / 输出 0.3M」（含 cache 分项 tooltip）；成本字段缺失时显示「成本不可用（网关未回传）」而非 $0.00
- [x] 2.2 验证报告汇总表新增「本链增量 token」行（合成器从 tokens.json 求和）

## 3. 预算告警与配置界面

- [x] 3.1 配置 `agents.token_budget_millions`（缺省 50，0=关闭）；收工检查处 80% 提醒 / 100% 升级告警（`_token_warn_80`/`_token_alert_100` 幂等标记，不自动冻结）
- [x] 3.2 config 页新增「Token 预算（百万）」数值输入（0-1000 校验，0 提示关闭），保存走热更新链路，浏览器实测

## 4. 单元测试

- [x] 4.1 覆盖：usage 提取累加（含 cache 分项）；异常 run 零计；80%/100% 一次性告警与标记持久；预算 0 关闭；「成本不可用」渲染
- [x] 4.2 用 v2-config-page 真实 jsonl 夹具回归提取数值（对照人工考古 42M）

## 5. 验证与打包

- [x] 5.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包

## 验证修复（第 1 轮失败）

- [ ] 阅读 `openspec/changes/add-cost-observability/verification-report.md`，定位「真实产品 Bug」并修复
- [ ] 修复后重跑验证确认通过
