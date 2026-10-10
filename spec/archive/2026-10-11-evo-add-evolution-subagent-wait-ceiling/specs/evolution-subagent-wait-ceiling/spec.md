# evolution-subagent-wait-ceiling 规格

## ADDED Requirements

### Requirement: 自进化车道无限等待后台子代理
run_evolution 派发 Claude Code CLI 时 SHALL 在该车道 env 中设置 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0，使「派子代理-等待-汇总」工作流不被 CLI 600 秒后台等待上限击杀；该设置 SHALL 仅作用于 evolution 车道（经 env_overrides），SHALL NOT 改动 runner 层全局默认。

#### Scenario: 子代理核查超 600 秒仍收齐
- **WHEN** 自进化 run 派出的后台子代理运行超过 600 秒
- **THEN** CLI 不再按 600 秒上限强杀子代理，主 run 等待其完成并正常汇总落盘产物

#### Scenario: 注入仅限 evolution 车道
- **WHEN** 其他维护车道（self_review / code_review 等）派发 CLI run
- **THEN** 其 env 中不因本能力引入 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0，run 超时行为与现状一致

### Requirement: 进化提示词前台派发兜底
agents/evolution.md 的执行模式 SHALL 明确约束：核查子代理 MUST 前台派发（同一回合内等待结论），收齐全部子代理结论前 MUST NOT 结束回合；分片结果 SHALL 即时落盘以便续跑。

#### Scenario: 模板含前台约束
- **WHEN** 按 agents/evolution.md 组装自进化 prompt
- **THEN** 提示词中包含「子代理前台派发、未收齐结论不结束回合」的明确约束文案

### Requirement: 上限击杀归因直指 600 秒上限
evolution 收尾在产物契约缺失判失败时，SHALL 嗅探本 run 转录尾部的 stderr 行；命中「Background tasks still running after 600s」签名时，失败 reason SHALL 追加该上限说明（含变量名），使失败归因直接指向 CLI 后台等待上限而非泛化「产物未写出」。

#### Scenario: 产物缺失且转录含 600 秒签名
- **WHEN** read_contract 判产物文件未写出，且本 run 转录尾部 stderr 含「Background tasks still running after 600s」
- **THEN** 对外失败文案（fenixd.py 经 _evolution_warn 直出）包含 600 秒后台等待上限的归因提示

#### Scenario: 无签名时归因不变
- **WHEN** 产物缺失但转录无该签名
- **THEN** 失败 reason 维持现状文案，不附加上限归因