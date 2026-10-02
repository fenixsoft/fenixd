# proposal — improve-placeholder-scan-discrimination

## Why

占位符残留检测器（core/agent_runner/prompt_builder.py:103-134 _fill_and_scan_placeholders）对**填充后全文**扫描残留 {xxx}、只扣除本次 values 键——注入值文本（code-review 台账条目引用的源码片段，如 f-string「{e}」、URL 模板「&doc=${doc}」）里的花括号字面量必然落网。回源实测：窗口内 10 条警告、全 log 77 条，抽验的全部高频键均为注入值合法引用字面量，零内容丢失；当前 12 个 agents/*.md 模板零漂移（历史唯一真漂移 evolution {epoch} 已由 commit 45675687 修复）。

后果：WARNING 无人消费（连续多日在 log）、且 evolution/self-review 车道把 todo.md 全文注入提示词，警告键名回流下游形成自指噪音；检测器本身零测试覆盖。真实缺陷是判别力：分不清「模板骨架真漂移」（值得告警）与「注入值字面量」（合法文本）。

## What Changes

- 检测器拆双通道：填充前对模板骨架扫描（findall(template) 与 values 键集作差）判「模板侧真漂移」，保留 WARNING 并补模板名与调用点；填充后残差判「注入值字面量」，降为 INFO 计数不再打 WARNING。
- 渲染断言测试：驱动真实构建器遍历 AGENT_TYPES 全集，断言模板通道零漂移（可拦住 {epoch} 类真漂移回潮）。

## Non-Goals

- 不做逐键白名单（全 log 已 60 键/49 组合，维护成本高且治标）。
- 不改 repair 车道纯 f-string 构建路径（本就不经扫描器，无模板漂移面）。
- 不处理 verify.yaml 配置级 {test_targets} 消毒（evo-add-codefix-test-targets-fallback-sanitization 已在飞）。