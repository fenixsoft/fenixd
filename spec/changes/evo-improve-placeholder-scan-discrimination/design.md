# design — improve-placeholder-scan-discrimination

## D1 双通道实现

_fill_and_scan_placeholders（prompt_builder.py:103-134）内拆两段：
1. 预扫描：_PLACEHOLDER_RE.findall(template) - set(values) → template_leftover（模板侧真漂移；当前 12 模板实测零漂移，无需预置豁免机制）；
2. 填充后残差：findall(out) - set(values) - template_leftover → 注入值字面量。
消息形态：WARNING 记 template_leftover（含 template_name + agent/label/context_id）；INFO 记注入字面量计数。函数签名加 keyword 实参（缺省 None 时退化为现行为），不破坏潜在调用方。
边界注记（评审修补）：注入值字面量与模板真漂移同键（{foo} 既在骨架未填充、又出现在注入值文本）时，残差扣除 template_leftover 会把该字面量一并归入模板通道——仅多计一条 WARNING，无 INFO 漏报，亦不影响返回值（return out 不变），保守方向可接受，不预置消歧机制。

## D2 模板名来源

调用点均已持有 agent_type；模板名 = AGENT_PROMPT_FILES[agent_type]（prompt_builder.py:41-55）。五个调用点（:347 主路径 / :1533 self-review / :1606 evolution / :1684 code-review / :1736 code-fix）各加一实参（即 D1 的 template_name keyword，取值 AGENT_PROMPT_FILES[agent_type]）。
澄清（评审修补）：五个调用点现传 agent_type 均在 AGENT_PROMPT_FILES 白名单内（:347 主路径收尾服务其余 8 个模板车道，self-review/evolution/code-review/code-fix 经 _build_prompt 独立分支到达各自调用点），直接索引安全、无缺键风险；函数内现有 agent_type 形参虽足以导出模板名，仍显式加 template_name keyword 是为兼容潜在非白名单调用方（缺省 None 退化为现行为，见 D1）——实现按 R2 五点全部传参，不二选一，验收以「WARNING 消息含模板名」行为契约为准。

## D3 测试驱动真实构建器

复用 tests/test_agent_prompt_files.py 的 make_runner + AGENT_TYPES 参数化手法（:44-69 惯例、sys.path.insert 头），不复刻 values 字面量（会与实现漂移）。落点：新文件 tests/test_prompt_placeholder_scan.py（tests/ 扁平 test_*.py 布局）。

## D4 明确不做逐键白名单

全 log 60 键/49 组合是移动靶；通道拆分后字面量自身降级，白名单仅剩「模板骨架已知合法字面量」这一理论需求，当前无实例、不预置机制。

## D5 风险

- INFO 噪音仍存在但退出 WARNING 消费面；后续如需可按车道采样。
- repair 车道不经扫描器（:370-371 走 _build_repair_prompt 纯 f-string），不属缺口，不扩。