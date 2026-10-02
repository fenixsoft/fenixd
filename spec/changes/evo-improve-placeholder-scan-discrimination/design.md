# design — improve-placeholder-scan-discrimination

## D1 双通道实现

_fill_and_scan_placeholders（prompt_builder.py:103-134）内拆两段：
1. 预扫描：_PLACEHOLDER_RE.findall(template) - set(values) → template_leftover（模板侧真漂移；当前 12 模板实测零漂移，无需预置豁免机制）；
2. 填充后残差：findall(out) - set(values) - template_leftover → 注入值字面量。
消息形态：WARNING 记 template_leftover（含 template_name + agent/label/context_id）；INFO 记注入字面量计数。函数签名加 keyword 实参（缺省 None 时退化为现行为），不破坏潜在调用方。

## D2 模板名来源

调用点均已持有 agent_type；模板名 = AGENT_PROMPT_FILES[agent_type]（prompt_builder.py:41-55）。五个调用点（:347 主路径 / :1533 self-review / :1606 evolution / :1684 code-review / :1736 code-fix）各加一实参。

## D3 测试驱动真实构建器

复用 tests/test_agent_prompt_files.py 的 make_runner + AGENT_TYPES 参数化手法（:44-69 惯例、sys.path.insert 头），不复刻 values 字面量（会与实现漂移）。落点：新文件 tests/test_prompt_placeholder_scan.py（tests/ 扁平 test_*.py 布局）。

## D4 明确不做逐键白名单

全 log 60 键/49 组合是移动靶；通道拆分后字面量自身降级，白名单仅剩「模板骨架已知合法字面量」这一理论需求，当前无实例、不预置机制。

## D5 风险

- INFO 噪音仍存在但退出 WARNING 消费面；后续如需可按车道采样。
- repair 车道不经扫描器（:370-371 走 _build_repair_prompt 纯 f-string），不属缺口，不扩。