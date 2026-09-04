# Tasks: 并行度设置与严格优先级并行调度

## 1. 调度核心：优先级感知派发

- [x] 1.1 改造 `core/pm_engine.py` 队列结构：`_run_queue` 条目改为 `(priority, spec_name, agent_type)`；`_enqueue` / `_enqueue_front` 从 STATE.md 读取 SPEC priority（默认 5）写入条目；`_enqueue_front` 保持「同档优先」语义（verifier 与 implementer 同 priority，档内 FCFS）
- [x] 1.2 重写 `_process_queue` 派发算法：锁内扫描队列，取就绪条目中最高优先级档（`queued_best`）；无运行任务时派发该档；有运行任务时仅派发与运行档相同优先级的就绪条目（同档补齐并行度），其它优先级一律不派发（严格不并行、不抢占）；每个派发占用槽位并受 `max_concurrent` 上限约束
- [x] 1.3 保持现有状态校验（implementer 需 ready、verifier 需 implemented）、状态转换与 worker 线程派发逻辑不变；验证 `_on_spec_ready` / `_on_spec_implemented` / `_on_spec_done`(fix 重验证) / `_on_spec_bug_found` 各入队路径均携带正确 priority

## 2. 并行度配置与 Dashboard

- [x] 2.1 复用 `agents.max_concurrent` 作为并行度：确认 `ConfigLoader` 正整数校验；更新 `config.template.yaml` 中 `max_concurrent` 注释为并行度语义（同优先级任务可并行至该值）
- [x] 2.2 扩展 `core/dashboard/data.py` 的 `read_config` / `write_config` 受管键至 `agents.max_concurrent`：合并逻辑白名单化，写回时保留 `agents` 下其它子键（subagent_model / max_retries / max_turns）及 `llm`、`gates` 等原值
- [x] 2.3 配置页前端新增并行度数字输入（复用现有 `GET/POST /api/config` 端点与保存逻辑），提交非法值（非正整数）由后端 400 拒绝；保存成功提示「重启 daemon 生效」

## 3. 测试与验证

- [x] 3.1 在 `tests/test_core.py` 新增优先级派发单元测试：高优先级先执行（P1 先于 P5）、高优先级到达不抢占但低优先级不新增、同优先级并行至并行度上限、不同优先级不并行（空槽不补低优先级）、同档补齐、全同优先级等价 FIFO+上限
- [x] 3.2 新增 verifier 紧随 implementer 的档内 FCFS 回归测试（验证顺序不回退）
- [x] 3.3 新增配置合并测试：写并行度后 `agents` 其它子键与 `llm`/`gates` 原值不变；非法并行度 POST 返回 400 且不写盘
- [x] 3.4 运行 `python3 -m pytest tests/ -q` 全量通过，无回归
- [x] 3.5 端到端验证：构造不同/相同 priority 的就绪 SPEC，观察派发顺序与并行度；Dashboard 修改并行度并重启 daemon 后生效；确认调度期间无并发竞态（多 worker 同时 _process_queue）
