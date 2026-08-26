## 1. max_turns 默认值与配置校验

- [x] 1.1 将 `.fenix/config.yaml` 的 `agents.max_turns: 150` 改为 `300`
- [x] 1.2 将 `core/config.py` 中 max_turns 的默认/fallback 值统一为 300（校验语义保持正整数），并同步 `config.template.yaml`（若存在）
- [x] 1.3 将 `core/agent_runner.py` 中两处 `_get_config("agents.max_turns", 50)` 的 fallback 改为 300

## 2. Dashboard 配置页编辑 max_turns

- [x] 2.1 在 `core/dashboard/data.py` 的 `_AGENTS_MANAGED_SUBKEYS` 与 `_SOURCE_KEYS` 中增加 `max_turns`
- [x] 2.2 在 `core/dashboard/static/app.js` 配置表单「并行度设置」区块（max_concurrent 输入框旁）新增 max_turns 数字输入框，只读展示来源，无配置时预填 300
- [x] 2.3 更新 app.js 保存逻辑：将 `agents.max_turns` 纳入 POST /api/config 回写对象（保留其它 agents 子键原值），非法值（非正整数）提交时由后端拦截返回 400 且不写盘
- [x] 2.4 验证 `GET /api/config` 返回包含当前 `agents.max_turns`，配置页正常展示与保存

## 3. verifier 断点续跑

- [x] 3.1 在 `core/agent_runner.py` 的 `_build_prompt` verifier 分支中，构造提示词前读取 `.fenix/verify-progress/<spec>.json`：存在且 `done > 0` 时生成断点段落（total/done/current），并将进度初始化指令改为「Step 0 写 done=<断点值>」与「从 done+1 场景继续、total 不变、逐场景递增」
- [x] 3.2 断点文件缺失 / `done == 0` / JSON 损坏时安全降级：不注入断点、不报错、全新开始（损坏文件忽略或移除，不污染后续 attempt）
- [x] 3.3 验证重试链路端到端：模拟 attempt 1 写到 done=5 后终止，attempt 2 提示词含断点信息，续跑完成写入 `done=total` 与 `.fenix-run-result.json`

## 4. 测试与打包

- [x] 4.1 运行 `python3 -m pytest tests/ -q` 确认无回归（含既有 config 与 dashboard 用例）
- [x] 4.2 为断点注入与 max_turns 默认值补充/更新单元测试（配置默认 300、断点降级分支）
- [x] 4.3 执行 `node --check` 校验前端改动、`bash scripts/package.sh` 生成新扩展包（若适用）