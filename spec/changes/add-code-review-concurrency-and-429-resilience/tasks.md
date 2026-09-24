## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification/infra_classify.py
  kind: modify
- path: tests/test_code_review.py
  kind: modify
- path: tests/test_provider_circuit.py
  kind: modify
- path: tests/test_provider_failover.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 全仓审查并发配置键

- [ ] 1.1 `core/config.py` 新增 `ConfigLoader.get_repo_code_review_concurrency`：读 `verify.repo_code_review_concurrency`，仅接受正整数 `int`（`bool` 不算），缺失/verify 节缺失/str/float/≤0 回退缺省 4；docstring 注明 MUST NOT 进 `resolve_config` 缺省填充列表（与 `get_impl_code_review_concurrency` 同款单点缺省约束）
- [ ] 1.2 `.fenix/config.template.yaml` 在 `verify:` 节 `impl_code_review_concurrency` 旁新增 `repo_code_review_concurrency: 4` 示例，注释注明语义（全仓审查并发：子代理扇出上限 + ocr scan --concurrency，缺省 4）
- [ ] 1.3 `tests/test_code_review.py` 的 `TestGetCodeReviewConfig` 新增用例：合法值生效 / str"8" 回退 / 0 回退 / true(bool) 回退 / float 回退 / 缺省 4（对照 impl 版既有用例风格）

## 2. 并发双通道注入（提示词扇出上限 + ocr scan 参数）

- [ ] 2.1 `core/agent_runner/maintenance_runs.py` 的 `run_code_review` 读取 `get_repo_code_review_concurrency` 并经 detail 传入 `_build_code_review_prompt`（键名 `repo_concurrency`）
- [ ] 2.2 `core/agent_runner/prompt_builder.py` 的 `_build_code_review_prompt` 注入 `{repo_concurrency}` 占位符（含未解析占位符残留告警同款防护），docstring 增补该键
- [ ] 2.3 `agents/code-review.md`「分批/并行审查的落盘纪律」段新增硬条款：同时「在飞」的审查子代理数 MUST ≤ `{repo_concurrency}`（波内并行上限、波次滚动推进，违反=run 判失败），`ocr scan` 命令示例加 `--concurrency {repo_concurrency}`
- [ ] 2.4 `tests/test_code_review.py` 新增用例：配置值为 4 时渲染提示词含「4」上限条款与 `--concurrency 4`；值为 2 时渲染 2；`{repo_concurrency}` 残留为零

## 3. Dashboard 设置界面与配置链路

- [ ] 3.1 `core/dashboard/data/config_admin.py` 的 verify 白名单与默认值聚合新增 `verify.repo_code_review_concurrency`（与 `impl_code_review_concurrency` 同款读写与来源标注）
- [ ] 3.2 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx` 新增「全仓审查并发」数字输入项，与既有「SPEC 审查并发」（impl 键）并列、分别保存，校验正整数
- [ ] 3.3 `core/dashboard/static/src/services/dashboard.ts` 同步配置类型定义与读写接口字段
- [ ] 3.4 `core/dashboard/static/` 下 `npm run build` 构建通过（dist 为运行时产物，不入库，构建成功即验证）

## 4. 429 限流分类与 provider 冷却

- [ ] 4.1 `core/agent_runner/provider_circuit.py` 新增常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS = 300` 与分类逻辑：错误文本命中 HTTP 429 / `[1302]` / `rate_limit` 任一签名判为限流错误（以 2026-09-24 真实错误文本 `API Error: Request rejected (429) · [1302][您的账户已达到速率限制，请您控制请求频率]` 作 fixture）；429 MUST NOT 计入 `PROVIDER_CIRCUIT_4XX` 计数
- [ ] 4.2 `classify_switch_error` 将限流错误纳入切换类错误（更新 docstring 分类清单），命中时 provider 进入限流冷却（复用 switch 冷却通道与候选跳过语义，冷却时长用 4.1 常量）
- [ ] 4.3 `core/pm_engine/verification/infra_classify.py` 中切换类错误描述同步（unrecognized_model/5xx/网络/429 限流）
- [ ] 4.4 `tests/test_provider_circuit.py` 新增用例：429 文本命中分类 / 429 不增 4xx 计数 / 冷却期内候选被链选择跳过 / 冷却到期探针复位

## 5. 429 打死 run 的自动重派

- [ ] 5.1 `core/agent_runner/runner.py` 的 attempt 失败分类消费点：终态归因为 429 限流且重派未超上限（常量 1）时，登记 `ratelimit_redispatch` 意图（provider 冷却到期后自动重派；重派计一次 attempt，受既有预算/escalation 守卫；run jsonl 标注重派缘由）
- [ ] 5.2 code-review 车道重派复用原 manifest（`run_code_review` 侧幂等保障既有：聚合读侧按 file 去重 + 提示词不重审纪律），运行记录可见重派缘由字段
- [ ] 5.3 `tests/test_provider_failover.py` 新增用例：429 终态触发重派登记 / 重派超上限走既有失败收场不再重派 / 非 429 失败不触发重派 / run jsonl 含重派标注

## 6. 回归与验证

- [ ] 6.1 全量相关单测通过：`pytest tests/test_code_review.py tests/test_provider_circuit.py tests/test_provider_failover.py tests/test_impl_code_review_tuning.py tests/test_impl_code_review_gate.py tests/test_code_review_scope_config.py`（禁读构建产物，basetemp 遵守 conftest 约定）
- [ ] 6.2 Dashboard 冒烟：构建产物起服务后设置页可见「全仓审查并发」输入项，修改保存后 config 落盘且「SPEC 审查并发」值不变（验证按 verify.yaml 场景执行，BASE_URL 用运行实例地址）
