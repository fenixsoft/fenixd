# 任务

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_verify_command_port.py
  kind: modify
```

## 1. 主树 command 实例路径

- [ ] 1.1 core/pm_engine/verification.py：新增 `_serve_command_in_main(spec_name, contract, scenarios_path)`——以 worktree 版 `_serve_command_in_worktree` 为蓝本逐行同构，去掉 `_ensure_serving_worktree` 供给与 worktree 清理、**删除 head 缓存复用段（`verification.py:535-542`）**，cwd 取 `str(self._pm.project_root)`；保留入口存在性预检、`{port}` 替换 + `FENIX_VERIFY_PORT` 注入、`CommandVerifyServer` 构造、失败回落、`_register_serving_instance` 登记、`_finalize_static` 收尾。缓存：**不复用、每验证新建实例**（主树工作区无「HEAD 未变 ⇒ 产物未变」保证，复用测得旧产物、违 BASE_URL 新鲜性铁律）；但**仍以 `spec_name` 为键写入 `_contract_static_servers`**（server/mode 元数据），供 `_evict_spec_serving` 终局回收——**禁用键 `"main"`**（该键为 static 主树共享实例专属，终局豁免）。
- [ ] 1.2 core/pm_engine/verification.py：分派点接线——`if serve and serve.kind == "command" and serve.cmd:` 分支中，`not wt_scope` 时 `return self._serve_command_in_main(...)`，不再穿透到 legacy；删除仅供 legacy 消费的 `start_cmd_override`/`serve_port_hint` 赋值。

## 2. legacy 归因措辞

- [ ] 2.1 core/pm_engine/verification.py：修正 legacy 端口改写日志——「场景 URL 端口 X 与应用实际端口 Y 不符（planner 臆测）」改为中性对齐措辞（如「场景声明端口 X 与框架分配端口 Y 不符，已改写对齐」），不含「planner 臆测」；逻辑不变。顺带清理代码库内其余同款误导归因措辞：`:963` 行注释与 `:2047` 行注释（「planner 臆测端口 → 应用实际端口」）一并改为中性描述——该措辞是本 SPEC 要消除的假信号的载体，注释残留会在后续维护中继续传播归因，需一并去除。

## 3. 回归测试

- [ ] 3.1 tests/test_verify_command_port.py：新增 `command + static_scope=main` 用例——走 `_serve_command_in_main`，`rewrite_scenarios_origin` 被调用把场景 origin 改写到注入端口，且不触发 legacy（`commands.start`/`_rewrite_scenario_port` 未被调用）。
- [ ] 3.2 tests/test_verify_command_port.py：新增 `command + main` 且 `serve.cmd` 未引用 `{port}` 用例——经进程归属发现（或邻近扫描）定位自绑默认端口的实例，场景 origin 对齐该端口。
- [ ] 3.3 tests/test_verify_command_port.py：新增/断言 legacy 端口改写日志不含「planner 臆测」措辞。
