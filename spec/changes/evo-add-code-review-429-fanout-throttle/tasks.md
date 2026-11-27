## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 缺省上限降档

- [x] 1.1 core/config.py：get_repo_code_review_concurrency（实测 :4969-4971）缺省值 4 → 2，读器语义与显式配置覆盖行为不变；docstring「一键两用」（ocr scan --concurrency 缺省并行度）补注同步降档声明。
- [x] 1.2 .fenix/config.template.yaml：repo_code_review_concurrency 模板示例值同步 4 → 2（遵守模板既有注释约束：示例值必须等于缺省值；注释内「正整数，缺省 4」文案同步改 2）。
- [x] 1.3 core/agent_runner/prompt_builder.py：审查 prompt 注入段 fail-open 回退值 4 → 2——detail 缺失/脏值回读读器路径自动跟随 1.1；ConfigLoader 导入失败分支硬编码 `repo_concurrency = 4`（实测 :2466 附近）改为 2，消除异常路径降档绕过。
- [x] 1.4 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx：REPO_REVIEW_DEFAULT_CONCURRENCY（:56，注释明示与 ConfigLoader 缺省同源）4 → 2；:161 空值回显与 :727 描述文案自动跟随，避免设置页与后端生效值漂移。

## 2. 429 记忆降档

- [x] 2.1 core/agent_runner/maintenance_runs.py：run_code_review 注入段（约 :3049-3063）生成 repo_concurrency 前，扫描最近一份同车道 run 归档 jsonl 尾部窗口，命中 429 终态子代理死亡（「429」「1302」「rate_limit」签名）则折减至 1；扫描缺失或异常按原配置值放行（fail-open）。
- [x] 2.2 agents/code-review.md：并行扇出上限段（:39）追加 run 内记忆条款——出现 429 子代理死亡后波内上限不得回升、重派间隔 ≥60 秒、同 run 第二次 429 后 ≥180 秒，违反沿既有「违反 = run 判失败」语义。
- [x] 2.3 agents/code-fix.md：在飞子代理分档段（:57-58）追加同款 429 记忆降档条款。

## 3. 收尾告警

- [x] 3.1 core/agent_runner/maintenance_runs.py：终态归因/收场段（约 :3611-3648 或 :3512 分支）扫描本 run jsonl 统计 429 终态子代理死亡数，≥3 时经 AdminStore.append_if_absent 直写单条告警（signal_type=review_subagent_ratelimit，dedup_key 含 run id，内容含死亡分片名）；少于 3 条不发，同 run 至多一条。

## 4. 测试

- [x] 4.1 tests/test_code_review.py：覆盖缺省降档（未配置项目注入值为 2）、prompt_builder fail-open 回退值（ConfigLoader 缺失分支注入 2）、上轮 429 记忆折减（有/无记录两形态）、收尾告警阈值（2 条不发 / 3 条单条直写）、扫描异常 fail-open；QualityPanel 常量断言 REPO_REVIEW_DEFAULT_CONCURRENCY=2。
