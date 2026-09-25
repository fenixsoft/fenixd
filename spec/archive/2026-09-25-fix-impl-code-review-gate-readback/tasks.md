# fix-impl-code-review-gate-readback — Tasks

## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: modify
- path: tests/test_impl_code_review_gate.py
  kind: modify
```

## 1. 抽校验体（双路径共用）

- [x] 1.1 `core/agent_runner/result_gate.py`：新增模块级私有函数 `_validate_code_review_report(cr_data, data, report_rel) -> str | None`，把现 `_check_impl_code_review_artifact` 中「`isinstance(cr_data, dict)` → status 白名单 → unavailable+非空 reason 放行 → findings 为 list → `code_review` 段存在 → dispositions 别名解析 → 逐条 disposition 白名单/reason 非空」整段**逐字搬移**为函数体（含既有注释），`report_rel` 仅用于归因文案拼接；行为零变化
- [x] 1.2 `_check_impl_code_review_artifact` 改为：开关/配置读取与 `data.get("code_review")` 无关的前置（enabled、wt_path/project_root 候选收集）留在原位，读到 `cr_data` 后一律 `return _validate_code_review_report(cr_data, data, report_rel)`；确认既有测试 `tests/test_impl_code_review_gate.py` 全部用例仍绿（纯重构回归门）

## 2. 双候选路径探测 + 新鲜度守卫

- [x] 2.1 `_check_impl_code_review_artifact` 签名增 `run_started_at: float | None = None` 与 `is_resumed_worktree: bool = False` 两个**带缺省**参数（缺省 None/False → 主树候选不做 mtime 硬拦，保持既有直接调用方兼容）
- [x] 2.2 候选路径收集：`wt_path` 非 None 时先加 worktree 候选；再经 `getattr(runner, "project_root", None)` 取根，**仅当 `isinstance(root, (str, Path))` 成立**时加主树候选（裸 `getattr`/`is None` 判定对 `MagicMock` 替身无效：其自动属性、`/` 与 `.is_file()` 均 truthy，`json.loads(mock.read_text())` 抛 `TypeError` 逸出既有 `except (OSError, json.JSONDecodeError)`）；按 `Path.resolve()` 去重（wt_path 与 project_root 相同时只留一个），去重后保留**先出现者**的校验模式（wt_path == project_root 时按 worktree 语义不做 mtime 硬拦，保现状）。**顺序不可倒置**（worktree 优先）。**候选集为空（wt_path 为 None 且 project_root 不可得）→ 直接 `return None`**（缺载体不校验，与现状同语义，MUST NOT 落到 2.4 缺失归因——见 spec「无 worktree 载体时不误判」场景）
- [x] 2.3 探测循环：逐候选 `is_file()` 命中即用——worktree 候选走现状「`read_text` + `json.loads`」并保持**不做 mtime 硬拦**；主树候选改走 `runner._check_artifact_json_file(path, "implementer", run_started_at, is_resumed_worktree=is_resumed_worktree)`，`err` 非 None 时**继续尝试下一候选**（而非直接判失败），解析异常沿用现状「无法解析」归因。循环 MUST 记住**「文件存在但未过校验」的首个 `err`**（含主树陈旧 `err`，其文案含「陈旧」，见 `_check_artifact_json_file` 的「陈旧残留」归因）。全部候选无有效数据时二分：曾命中「存在但非法/陈旧」的候选 → **返回该 `err`**（MUST NOT 折叠成缺失归因，否则 spec「主树报告陈旧 → 文案 MUST 指明陈旧」场景与 3.1③ 不可满足）；所有候选文件**均不存在** → 返回 2.4 缺失归因
- [x] 2.4 缺失归因文案：`exit 0 但收尾审查报告缺失（impl-code-review-gate）: .fenix/verify-progress/<spec>/code-review.json（已探测 worktree 与主树两个位置）`——保留 `报告缺失` 与 `code-review.json` 字样（既有测试断言依赖）；**仅用于「所有候选文件均不存在」**
- [x] 2.5 `_check_impl_result_artifact`（`result_gate.py:746-752`）调用点补传 `run_started_at=run_started_at, is_resumed_worktree=is_resumed_worktree`（二者已是该函数形参，直接透传）

## 3. 测试

- [x] 3.1 `tests/test_impl_code_review_gate.py` 新增用例（沿用既有 `_mock_runner` / `_gate` 样式，并扩充 `_mock_runner` 使 `runner.project_root` 指向 `tmp_path`，**且 MUST 把 `runner._check_artifact_json_file` 接到模块级真实实现**——`_mock_runner` 现为裸 `MagicMock`（`tests/test_impl_code_review_gate.py:273-278`），不接线则各条主树回退用例的 `err` 恒为非 None mock 值 → ② 恒失败）：① worktree 有报告 → 放行（既有用例覆盖，确认不回归）；② worktree 缺失 + 主树新鲜合法报告 → 放行；③ worktree 缺失 + 主树报告 mtime 陈旧（早于 `run_started_at - grace`）且非 resume → 判失败且文案含「陈旧」；④ 同 ③ 但 `is_resumed_worktree=True` → 放行；⑤ 两处皆缺 → 判失败且文案同时含 `报告缺失`、`code-review.json` 与「worktree 与主树」；⑥ `runner.project_root` 非 Path 载体（属性缺失 / `MagicMock` / `None`）→ 跳过主树候选、不抛异常、行为等价现状；⑦ `wt_path` 与 `project_root` 相同的去重场景只判定一次（且按 worktree 语义不做 mtime 硬拦）
- [x] 3.2 `tests/test_impl_code_review_gate.py` 复核既有断言：`test_enabled_report_missing`（断言 `报告缺失` + `code-review.json`）与 `test_enabled_report_invalid_json` 在新路径下仍成立；如 `_mock_runner` 现无 `project_root`，补齐后须确保既有 6 条 `test_enabled_*` 用例语义不变

## 4. 收尾验证

- [x] 4.1 跑受影响测试集（`tests/test_impl_code_review_gate.py`、`tests/test_agent_runner_gate.py`、`tests/test_impl_code_review_tuning.py`、`tests/test_characterization_agent_runner.py`）全绿
- [x] 4.2 跑有界全量回归 `python3 bin/run_full_suite.py --timeout 3600`，确认零本次引入失败（允许既有环境性失败，须逐一列举并说明与本次改动无关）
