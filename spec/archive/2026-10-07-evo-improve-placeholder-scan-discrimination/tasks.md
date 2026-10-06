## Deliverables

```yaml
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_prompt_placeholder_scan.py
  kind: new
```

## 1. 检测器双通道拆分

- [x] 1.1 core/agent_runner/prompt_builder.py：_fill_and_scan_placeholders 拆两段扫描——填充前对模板骨架扫描（findall(template) 与 values 键集作差）判「模板侧真漂移」，填充后残差判「注入值字面量」；函数签名加 keyword 实参向后兼容，填充行为保持无条件 return out 不变
- [x] 1.2 core/agent_runner/prompt_builder.py：模板侧真漂移保留 WARNING 且消息补模板名（AGENT_PROMPT_FILES[agent_type]）与调用点 label/context_id；注入值字面量降为 INFO（或计数）不再打 WARNING
- [x] 1.3 core/agent_runner/prompt_builder.py：五个经扫描器调用点（主路径 spec、self-review、evolution、code-review、code-fix）全部补传模板标识实参，不得只改单车道

## 2. 测试

- [x] 2.1 tests/test_prompt_placeholder_scan.py：按 AGENT_TYPES 参数化驱动真实构建器（make_runner 夹具 + _build_prompt）渲染，断言全部模板渲染后模板通道零残留（无「提示词占位符未解析」WARNING）
- [x] 2.2 tests/test_prompt_placeholder_scan.py：判别行为单测——构造模板缺键场景断言 WARNING 且消息含模板名；构造 values 携带 {xxx} 字面量场景断言不打 WARNING 仅 INFO