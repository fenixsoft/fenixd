## Deliverables

```yaml
- path: core/verify_engine/runner.py
  kind: new
- path: core/verify_engine/web_runner.py
  kind: new
- path: core/verify_engine/api_runner.py
  kind: new
- path: core/verify_engine/api_assertions.py
  kind: new
- path: core/verify_engine/cli_runner.py
  kind: new
- path: core/verify_engine/cli_assertions.py
  kind: new
- path: core/verify_engine/engine.py
  kind: modify
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/verify_contract.py
  kind: modify
- path: core/verify_contract_template.yaml
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_scenarios.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: agents/verifier.md
  kind: modify
- path: agents/planner-judge.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: docs/help/05-verification.md
  kind: modify
- path: docs/help/08-config.md
  kind: modify
- path: docs/help/02-concepts.md
  kind: modify
- path: docs/help/01-quick-start.md
  kind: modify
- path: tests/test_verify_multi_kind.py
  kind: new
- path: tests/test_verify_api_runner.py
  kind: new
- path: tests/test_verify_cli_runner.py
  kind: new
- path: tests/test_verify_contract.py
  kind: modify
- path: tests/test_verify_scenarios.py
  kind: modify
```

## 1. PR1：引擎 Runner 化等价重构

- [x] 1.1 新建 `core/verify_engine/runner.py`：Runner 接口（`kind`/`validate`/`setup`/`execute`/`teardown`/`probe_env`）与按 kind 注册表；模块注释写明「调度器不得含 per-kind 执行分支」约定
- [x] 1.2 `core/verify_engine/scenarios.py`：`TestScenario.kind` 字段（缺省 `web`、from_dict 透传、取值 ∈ web/cli/api 校验）；VALID_ACTIONS/VALID_ASSERTIONS 组织为 per-kind 词表常量（web 词表内容不变）
- [x] 1.3 新建 `core/verify_engine/web_runner.py`：BrowserManager 生命周期、extension 健康检查、per-scenario context、console/network 错误注入、截图取证、视觉对比、推流探针整体归位，行为不变（navigate 硬要求校验随迁）
- [x] 1.4 `core/verify_engine/engine.py` 瘦身为纯调度：验收门逐场景委托 Runner.validate、按场景集实际 kind lazy setup/teardown（纯 CLI/API 轮次不启浏览器）、结果组装、状态判定/进度写盘/报告构建/环境门后置分类骨架保留
- [x] 1.5 回归验证：现有 verify 相关测试全绿（test_verify_contract / test_verify_scenarios / test_verify_command_port / test_verify_report_gate 等）+ Dashboard fixture 验证配方回归；新增 `tests/test_verify_multi_kind.py` 覆盖 kind 缺省/非法值/调度分派/lazy setup

## 2. PR2：ApiRunner 与契约形态反推

- [x] 2.1 API 词表常量 + 新建 `core/verify_engine/api_assertions.py`：status_code / json_path / response_header / body_contains / json_schema / latency_under（第4层）/ sse_event_matches / sse_event_count；jsonschema 缺失时 json_schema 断言验收期报错打回
- [x] 2.2 新建 `core/verify_engine/api_runner.py`：`http_request`（method/url/headers `{env:VAR}` 插值/body/body_type/timeout/as）与 `sse_connect`（url/duration/as，实现复杂度高时允许降为 fast-follow 并在本任务登记）步骤；httpx 每场景独立 client；响应命名捕获与 `response` 字段引用；证据 64KB 截断；连接失败类=环境候选
- [x] 2.3 `core/verify_contract.py`：base_url 统一供给（取代 `_locate_app_base_url` navigate 文本正则考古）；`http_request`/`sse_connect` URL origin 全量改写（路径保留）；模块注释（权威字段文档）与 `core/verify_contract_template.yaml` 同步扩展三种形态说明
- [x] 2.4 `core/pm_engine/verification.py`：serve/ready 按场景集 kind 组成反推——纯 cli 跳过 serve/ready 且不回退 commands.start（`_ensure_app_reachable` 短路）；含 web/api 必须（缺失=明确错误打回 plan）；混合照常起
- [x] 2.5 新建 `tests/test_verify_api_runner.py`（本地测试 HTTP 服务夹具）：词表校验/命名捕获/origin 改写/serve 反推/blocked-env 探针；`tests/test_verify_contract.py` 补形态反推用例
- [x] 2.6 httpx 依赖接入（deps_mode 通道声明与安装验证）

## 3. PR3：CliRunner 与无 serve 形态

- [x] 3.1 CLI 词表常量 + 新建 `core/verify_engine/cli_assertions.py`：exit_code / file_exists / output_match / file_content / json_output / dir_contains（分层语义与字段口径按 spec）
- [x] 3.2 新建 `core/verify_engine/cli_runner.py`：`run` 步骤（字符串=shell/列表=argv 复用 prepare 解析约定、cwd 相对验证树根、env/stdin/timeout/as）；非零退出码不判步骤失败；超时杀进程组=步骤失败；信号死亡与 FileNotFoundError=error；`FENIX_VERIFY_BASE_URL`/`FENIX_VERIFY_PORT` 自动注入且框架值优先；stdout/stderr 64KB 截断
- [x] 3.3 新建 `tests/test_verify_cli_runner.py`：语义矩阵单测（true/false/echo 假命令——非零退出不误判、超时 fail、信号死亡 error、二进制缺失 error、截断、env 注入框架值优先、混合场景集跨 kind depends_on 调度）
- [x] 3.4 验收门 per-kind 校验接线：未知 kind/步骤不属于本 kind 词表/必填字段缺失/含 web-api 但无 serve 配置，错误消息带「支持: …」词表速查

## 4. 下游兼容与前端

- [ ] 4.1 report.json scenarios 元素透传 `kind`；`screenshots`/`visual_results` 空列表 schema 兼容（summary 口径不变）
- [ ] 4.2 `core/verify_scenarios.py`：`ScenarioEntry` 可选 `kind` 字段（to_dict 序列化、读侧缺省 web、冻结集补齐/合并携带）；`tests/test_verify_scenarios.py` 补用例
- [ ] 4.3 verdict 链回归夹具（不改 `verdict_check.py`）：cli/api 失败场景的 assertion_triage 四分类、product-bug 拦截豁免、无截图证据合规三不变量
- [ ] 4.4 `core/dashboard/static/src/pages/projects/detail.tsx`：场景 kind 徽章（web/cli/api）、断言详情字段驱动渲染（不按 kind 分支组件）、截图区空占位说明
- [ ] 4.5 dashboard 前端构建与相关测试回归（dist 出 git，merge 后框架自动重建，不提交 dist）

## 5. planner 指导与提示词中立化

- [ ] 5.1 `agents/planner-plan.md`：kind 选择判定树（页面→web / 端点→api / 命令落盘→cli / 混合拆场景+depends_on）、三套词表摘要（标注权威源=core/verify_engine/scenarios.py VALID 常量）、cli 非零退出不判失败与 api 响应命名捕获特异规则、「HTTP 端点验证用 api 场景」治理指引
- [ ] 5.2 `agents/verifier.md` / `agents/planner-judge.md` / `agents/fast-track.md`：取证措辞「截图」→「证据（截图/命令输出/HTTP 响应体）」中立化；遵循 prompt 双落点约定（先 merge main + merge-tree 自证零冲突）
- [ ] 5.3 交互契约非 web 场景空转回归：`collect_display_declarations` 对 run/http_request 步骤不误报、covers 空登记合法

## 6. docs/help 文档更新

- [ ] 6.1 `docs/help/05-verification.md`：新增多形态验证章节（三 Runner 分工、契约形态按场景集反推、kind 选择、纯 CLI 无 serve 形态、CLI/API 证据形态），中立化「验证=浏览器」表述
- [ ] 6.2 `docs/help/08-config.md`：verify.yaml 契约说明与多形态示例核对更新
- [ ] 6.3 `docs/help/02-concepts.md` / `docs/help/01-quick-start.md`：验证相关表述中立化核对
