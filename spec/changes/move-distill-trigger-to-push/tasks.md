## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/archive_commit.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_prompts/distill.md
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: bin/fenix_archive.py
  kind: modify
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_spec_approve_push.py
  kind: modify
- path: tests/test_knowledge.py
  kind: modify
- path: tests/test_spec_archive.py
  kind: modify
- path: tests/test_knowledge_distill_resume.py
  kind: modify
- path: tests/test_move_distill_trigger_to_push.py
  kind: new
```

## 1. 触发点迁移

- [ ] 1.1 `core/pm_engine/engine.py` `approve_push` 成功转移（done→pushed 落账后）挂载 `dispatch_distill(proot, spec_name)`：延迟导入+`distill=` 替身参数（仿 archive_commit 既有模式）；fail-open（异常只告警不影响返回值）；幂等 skip/非 done/退避期/不存在各早退分支均不派发
- [ ] 1.2 `core/archive_commit.py` 移除蒸馏挂载段（`commit_archive_move` 不再调用 dispatch_distill，返回结构保留 `distill: None` 键兼容既有消费方），docstring 同步更新触发语义
- [ ] 1.3 `tests/test_spec_approve_push.py`：成功转移→派发被调用一次；幂等回放/非 done/退避期→不派发；派发抛异常→approve_push 返回值与状态转移不变

## 2. 蒸馏输入双态解析

- [ ] 2.1 `core/knowledge.py`：`_gate_distill` 存在性检查改双态（changes/ 优先、archive/ 兜底，双缺拒绝 reason 保留 `archive-dir-missing` 字面量）；`build_distill_prompt` 动态段按双态探测结果给真实绝对路径，「本次待蒸馏的归档」改「本次待蒸馏的 SPEC」；docstring 语义标注（形参名 archived_names 保留不改，注明=蒸馏源名）
- [ ] 2.2 `core/knowledge_prompts/distill.md`：开篇语境改「SPEC 刚 push 完成进入终态（稍后由时效归档）」；sources 行与溯源链接契约改指 `spec/changes/<名>/`；「只给真实存在的目录加链接」守则同步；改写对照 `validate_knowledge._check_links` 正则与 knowledge_audit 检查逻辑，不引入第三种链接形态；溯源行保持现行全角括号纯文本形态、仅改路径段（模板 line 46 的 markdown 链接形态与在库真实页面不符，MUST NOT 借机「统一」成 markdown 链接——`_check_links` 按页面相对路径解析必然误报死链）
- [ ] 2.3 `tests/test_knowledge.py`：push 态（changes/ 存在）门控放行+prompt 路径正确；归档态（仅 archive/ 存在）门控放行+prompt 路径兜底正确；双缺拒绝 reason；模板契约段与 `_check_links` 一致性用例（模板示例链接过 `_check_links` 不报违规）

## 3. 归档改写 pass 与审计兼容

- [ ] 3.1 新增溯源改写器单函数（core/knowledge.py 内，多调用点共用禁复制粘贴）：输入（proot, spec 名, 实际归档目录名），扫描 `spec/knowledge/` 全页将 `spec/changes/<名>` 精确替换为 `spec/archive/<date-name>`（含 sources 行与正文溯源行，两种形态均为纯文本命中），返回替换文件清单；替换匹配 MUST 带名字右边界（命中后随非 `[A-Za-z0-9._-]` 字符或串尾），防前缀同名 SPEC 误伤（真实在库例：merge-back ↔ merge-back-precheck），`tests/test_move_distill_trigger_to_push.py` 补前缀同名不误伤用例；异常抛给调用方（fail-open 决策在调用方）
- [ ] 3.2 改写器全调用点接线（commit_archive_move 四处物理调用点同覆盖）：`bin/fenix_archive.py`（CLI）、`core/dashboard/data/spec_archive.py` 的 archive_spec（daemon R1/R2/R3 自动归档主线经此）与 soft_delete_spec（软删除命名 `<名>-<unix>`，改写器按实际归档目录名注入、命名无关）在目录移动成功后、归档提交前调用改写器，知识页改动并入同一 `[fenix] archive:` 提交；改写异常告警留痕不阻塞归档
- [ ] 3.3 `core/knowledge_audit.py` 溯源检查核对：grep 对 ARCHIVE_DIR 的路径锚定引用，放宽为「链接目标目录存在」两态等价（若检查器已无锚定则仅在测试锁定，不硬改）
- [ ] 3.4 `tests/test_spec_archive.py` + `tests/test_move_distill_trigger_to_push.py`（new）：归档→改写落库同提交；改写异常→归档照常+告警；知识页链接指向 changes/ 时 `validate_knowledge` 与 audit 均零违规（两态等价锁定）
- [ ] 3.5 `core/knowledge.py` `validate_knowledge` sources 分支（origin=archive 锚定，knowledge.py:447-465）：sources 前缀校验放宽为 changes/ 与 archive/ 两态均合法（目录存在性与越界复核保留，防穿透强度不降），防 push 态蒸馏页被判「sources 非归档路径」烧尽修正轮；`tests/test_knowledge.py` 补两态 sources 用例（changes 态 sources 过校验、archive 态行为不变）

## 4. 恢复重派与端到端回归

- [ ] 4.1 `tests/test_knowledge_distill_resume.py`：pending 批恢复重派时 SPEC 已归档→双态兜底命中 archive/、批正常执行；SPEC 仍在 changes/→按 changes/ 执行
- [ ] 4.2 端到端回归：蒸馏族全量（test_knowledge*.py）+ 归档族（test_spec_archive*.py/test_spec_approve_push.py）零回归；`python3 -m compileall core/ bin/` 通过；全仓 grep `commit_archive_move` 消费方确认返回结构兼容（distill 键恒存在）
