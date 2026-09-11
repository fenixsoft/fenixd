# Tasks: add-verify-preflight-gate

## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_verify_preflight_gate.py
  kind: new
```

## 1. 入口存在性预检（D1）

- [x] 1.1 `core/verify_contract.py` 新增纯函数 `resolve_entry_path(cmd: str, cwd: Path) -> Optional[Path]`：shlex.split 解析，可执行 ∈ {node, nodejs, tsx, ts-node, bun, deno} 且命令无 shell 元字符（`&&` `||` `|` `;` `>` `<` `$(` `` ` ``）时取第一个非 flag 参数按 cwd 解析绝对路径；其余形态返回 None。纯函数零 IO（文件存在性由调用方检查，便于测试）。
- [x] 1.2 同文件新增 `entry_preflight_error(cmd: str, cwd: Path) -> Optional[str]`：调 resolve_entry_path，解析出路径且文件不存在时返回错误串（含缺失路径全文 + 同目录 `*.js`/`index.js` 存在候选提示）；None=放行。
- [x] 1.3 `core/pm_engine/verification.py` `_serve_command_in_worktree` Popen 前（L548 附近）接入 `entry_preflight_error(cmd_str_transformed 前, cwd=wt)`——注意用 {port} 替换前的原 cmd 检查（{port} 不在路径段）；失败返回 `(False, False, err)` 并写 verify_contract_missing 信号（description 前缀「入口存在性预检失败」，evidence 含 cmd 原文）。
- [x] 1.4 `core/pm_engine/verification.py` `_ensure_app_reachable` 兜底 spawn Popen 前（L860 附近）同样接入（cwd=项目根）；失败走 `_escalate_env_blocked` 既有路径 + verify_contract_missing 信号，场景执行数为 0。
- [x] 1.5 复合命令/无法解析形态验证：构造 `npm run build && node x.js`、`python -m x` 样例确认返回 None 放行（零误杀）。

## 2. 契约消费期轻量自证（D2）

- [x] 2.1 `core/verify_contract.py` 新增 `selfcheck_contract_light(project_root, logger=None) -> Optional[str]`：读 `.fenix/verify-serving/contract_selfcheck.json` mtime_ns 快照一致→None；serve 段合法性（kind 枚举/static root 存在/command cmd 非空）+ ready 探针鉴别力自检（复用 probe_ready 既有函数）；不执行 prepare、不起实例；通过写快照、失败返回错误串不写快照。
- [x] 2.2 `core/pm_engine/verification.py` `_run_three_stage_verification` 阶段 2 前接入：契约存在且 selfcheck 返回错误 → fail-fast（同 D1 信号通道），场景执行数为 0。
- [x] 2.3 mtime 变化闭环测试：改 verify.yaml 内容（touch 更新 mtime）→ 下轮重自证；selfcheck.json 属 gitignore 运行时产物确认不入 git status。

## 3. 兜底 spawn 证据捕获（D3）

- [x] 3.1 `_ensure_app_reachable` 兜底 Popen（L860）：DEVNULL 改为 boot.log 文件句柄（`.fenix/verify-serving/<spec>-boot.log`，启动前 truncate），探活最终失败分支读尾部 ≤2KB 附入返回错误串（经既有 _escalate_env_blocked 自动进 evidence）。
- [x] 3.2 `CommandVerifyServer` 构造可选 boot 句柄参数，worktree 路径同样落盘；failure_note 机制不变。

## 4. planner 契约 findings 通道（D4）

- [x] 4.1 `core/verify_engine/scenario_static_check.py` 新增 `scan_contract(project_root) -> list[dict]` 与 `write_contract_findings(project_root, spec_name, findings)`：初始规则表 serve_entry_missing（D1 同源解析器，severity=high）/ serve_entry_vs_start_mismatch（对比 package.json start script，info）/ serve_entry_no_port_injection（info，与 load 侧 warning 同判据）；落盘 `.fenix/verify-progress/<spec>/contract_findings.json` 覆盖写；异常记 WARNING fail-open。
- [x] 4.2 `core/pm_engine`（engine.py 或 verification.py 的出题完成处）：planner-plan 产物验收通过后调用 scan_contract（try/except 全包裹，不阻断出题）。
- [x] 4.3 `core/agent_runner/prompt_builder.py` 新增 `_contract_findings_section(spec_name)`（克隆 `_scenario_static_findings_section` 骨架：逐条 rule_id/severity/message/evidence + 「机械检出、处置前以源码核实」声明），挂载 Administrator 处置派发 prompt；findings 缺失/为空/损坏返回空串零注入。

## 5. 测试与收尾

- [x] 5.1 新增 `tests/test_verify_preflight_gate.py`：resolve_entry_path 各形态（node 单脚本/flag 参数/复合命令/非 node 运行时/shlex 失败）；entry_preflight_error 存在与不存在；selfcheck mtime 快照命中与失效；scan_contract 三规则（mock 文件布局）；_contract_findings_section 零注入与有情报注入（patch 用户级常量，参照 fenixd-selfreview-tests-home-sensitive 处方）。
- [x] 5.2 与 add-main-tree-deps-provision 边界对齐检查：若其已落地，确认预检调用点在其供给动作之后（供给 → prepare → 预检 → spawn 顺序）；未落地则留注释锚点。
- [x] 5.3 全量回归 `pytest tests/test_verify_preflight_gate.py tests/test_pm_verification.py tests/test_verify_contract.py tests/test_verify_command_port.py` 通过，既有验证链测试零破坏。
