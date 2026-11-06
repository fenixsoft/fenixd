## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: agents/knowledge-distill.md
  kind: modify
- path: tests/test_knowledge_distill_run_artifacts.py
  kind: modify
- path: tests/test_harness_one_shot_forms.py
  kind: modify
```

## 1. 蒸馏执行器：spawn 返回值扩展与总结提取

- [ ] 1.1 `_spawn_once`/`_spawn_and_wait` 成功路径改为三元组 `(ok, err, stdout)`：`outcome.stdout` 原文随成功返回（失败路径第三位恒 None/空，error 组装不变）；全部解包点同步适配——`_spawn_and_wait` 内部对 `_spawn_once` 的两处解包（成功解包与 bare-model 重试段 `ok_retry, err_retry = ...`）改三元解包、主蒸馏调用点（`_run_batch` 主循环）改三元解包承接 stdout、折叠调用点（折叠前置段 `ok, err = self._spawn_and_wait(...)`）适配为忽略第三位
- [ ] 1.2 新增纯函数 `_extract_distill_summary(stdout: str) -> str`：剥除尾部 `KNOWLEDGE_DISTILL_DONE` 标记行（标记缺失空转不报错）、首尾空白归一、超 2000 字符截断加「…（截断）」后缀（上限为模块常量）；空输入返回空串
- [ ] 1.3 主蒸馏成功路径（校验通过且 commit 落库分支，`result["ok"] = True` 旁）装配 `result["summary"] = _extract_distill_summary(stdout)`；空串不写键

## 2. 产物终态行与提示词契约

- [ ] 2.1 `_distill_run_artifact_close` ok 分支的终态 `result` 行新增 `"result"` 字段（值取 `result.get("summary")`，非空字符串才写该键；字段名必须为 `result` 对齐读侧 `_run_tail_insights` 契约，error 分支不动）
- [ ] 2.2 `agents/knowledge-distill.md` 完成标准段（第 7 步附近）契约升级：自查通过后先输出简短工作总结（本轮蒸馏了哪些能力页/ADR、新增或修订了哪些规则要点，markdown、建议 ≤20 行），最后单独一行输出 `KNOWLEDGE_DISTILL_DONE`（stdout 最后一行）；折叠 prompt（`build_inbox_fold_prompt`）不动

## 3. 测试

- [ ] 3.1 `tests/test_knowledge_distill_run_artifacts.py` 增补：成功批终态行带 `result` 字段且与注入 stdout 剥标记后一致；stdout 空/仅标记行时不写该键且批成功不受影响；spawn 失败批终态行无总结文本
- [ ] 3.2 `tests/test_harness_one_shot_forms.py` 两处 `ok, err = ..._spawn_and_wait(...)` 解包适配三元组（成功支断言第三位为 stdout 文本、失败支第三位为空）
- [ ] 3.3 `_extract_distill_summary` 单测：剥标记、截断上限、空输入三分支；全量跑 `pytest tests/test_knowledge_distill_run_artifacts.py tests/test_harness_one_shot_forms.py tests/test_knowledge.py tests/test_knowledge_e2e.py tests/test_knowledge_distill_resume.py` 回归通过
