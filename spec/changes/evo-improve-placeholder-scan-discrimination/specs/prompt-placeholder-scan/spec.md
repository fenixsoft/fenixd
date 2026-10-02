# prompt-placeholder-scan

## Requirements

### R1 双通道判别

- _fill_and_scan_placeholders MUST 拆两段：填充前对模板骨架扫描占位符（findall(template) 与 values 键集作差）判「模板侧真漂移」；填充后残差判「注入值字面量」。
- 模板侧真漂移 MUST 保持 WARNING 级别，且消息 MUST 含模板名（由 AGENT_PROMPT_FILES[agent_type] 导出）与调用点 label/context_id。
- 注入值字面量 MUST 降为 INFO（或计数），MUST NOT 再打 WARNING。
- 填充行为 MUST 保持现状（无条件 return out，不阻断派发）。

### R2 调用点覆盖

- 五个经扫描器的调用点（主路径 spec、self-review、evolution、code-review、code-fix）MUST 全部传入模板标识实参；MUST NOT 只改单车道。

### R3 渲染断言

- tests MUST 驱动真实构建器（make_runner 夹具 + _build_prompt，按 AGENT_TYPES 参数化）断言：全部模板渲染后模板通道残留为空（无「提示词占位符未解析」WARNING）。
- tests MUST 覆盖判别行为：模板缺键场景断言 WARNING 且含模板名；values 携带 {xxx} 字面量场景断言无 WARNING。

## Scenarios

1. **模板真漂移**：某模板新增 {foo} 而构建方未填充 → 渲染期 WARNING，消息含模板名与调用点，可直达模板文件。
2. **注入值字面量**：台账条目 description 引用源码「{e}」字样注入 code-fix 提示词 → 无 WARNING（仅 INFO 计数），派发不受影响。
3. **回潮拦截**：向 agents/evolution.md 塞回未填充占位符（{epoch} 案回潮）→ 渲染断言测试失败。
4. **全车道回归**：AGENT_TYPES 全集真实构建渲染 → 模板通道零漂移。