## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/data/quality_gates.py
  kind: modify
- path: docs/help/13-model-chain-ops.md
  kind: new
- path: docs/help/README.md
  kind: modify
- path: tests/test_impl_selfcheck_model_probe.py
  kind: new
```

## 1. 收工自证 CLI

- [x] 1.1 `core/agent_runner.result_gate` 增加 `__main__` CLI（`--selfcheck <结果文件路径>`）：直接复用生产校验函数对象（非复制逻辑），退出码 0=PASS / 1=FAIL，FAIL 逐条输出违规明细（字段路径+期望形态）到 stderr；worktree 内零网络零 daemon 依赖可跑；参数缺失/文件不存在输出用法并以非零码退出
- [x] 1.2 prompt_builder 收尾检查注入段追加：自检完整命令与「非零退出不得收工、按 stderr 明细修复后重跑至 0」强制措辞；dispositions 合法正例 `[{"disposition": "fixed"}, {"disposition": "deferred", "reason": "..."}]` 与非法反例 `["fixed", "fixed"]` 逐字对照；status 枚举与必填键固化说明（以校验体为单源）
- [x] 1.3 单测（落 `tests/test_impl_selfcheck_model_probe.py`）覆盖：字符串数组 dispositions 被拦（明细含条目序号）、修复后 0 退出、合法文件零副作用、自检与 daemon 硬门同源判定一致

## 2. 拒模型快速 failover

- [x] 2.1 unrecognized_model 错误识别（stderr `[claude-code:unrecognized_model]` 或等价结构化类别；复用既有 `classify_switch_error`/候选链前进/switch 冷却机制，MUST NOT 新建平行切换路径）：命中即记 WARNING（provider/model/run_id）并沿该 agent 类型模型链原地切换下一可用模型继续当前 run，不整轮重派、不递增 transient/同因重派计数
- [x] 2.2 链尾模型仍被拒时按既有失败路径收场且归因含全链模型不可用语义，派发器 MUST NOT 对该归因走同因重派（阻断「冷却复位→再撞」循环）；5xx/超时/黑洞等其余 provider 错误处理路径行为不变（回归断言固化）
- [x] 2.3 `.fenix/config.template.yaml` 链卫生（评审实核：模板本无活动模型链定义，链在运行时 `.fenix/config.yaml`）：断言模板不含 `maomaoai + deepseek-v4.1-flash` 组合条目（单测固化），并在模板 models 注释示例处加一行拒模型警示注释（模板唯一实际改动）；运行时各链摘除该条目与「摘除后各链剩余条目 ≥3」核对项写入运维文档人工步骤
- [x] 2.4 新增 `docs/help/13-model-chain-ops.md` 并在 `docs/help/README.md` 完整目录表登记（#13 一行）：摘除理由（12 次拒模型实测）、恢复条件、运行时 `.fenix/config.yaml` 的人工同步修改步骤、及「在 `.fenix/todo.md` 登记提醒」的指示（人工步骤仅入文档，实现轮不改运行时配置与 todo.md——implementer 车道无主树写授权）
- [x] 2.5 单测（落 `tests/test_impl_selfcheck_model_probe.py`）覆盖：首选拒立即切链不重派、全链拒收场归因且不同因重派、其余错误路径回归不变、模板无该组合条目且含警示注释

## 3. 回归双跑合并

- [x] 3.1 prompt_builder 收尾段全量回归措辞改为降级路径（「全量回归由验证链执行；仅当确认框架侧回归产物不可用时才在 run 内执行并落盘」），frontend-build / interaction-contract 两项自查要求不变
- [x] 3.2 框架侧回归产物指纹 stamp + 读侧优先级：`core/regression.py` 写快照（`write_result`）时 stamp `(branch, merge_base, head_commit)` 指纹字段（现有 `last-run.json` 快照无分支字段，评审实核）；读侧 quality-gates 合成的 full-suite 门数据源优先级：框架侧回归产物（带分支指纹校验，指纹陈旧或存量快照无指纹字段按不可见）> quality-gates.json run 内自查值 > pending；任一来源异常 fail-open 逐级回落，键名全集与状态枚举零变化
- [x] 3.3 断言固化：result_gate / 交付物守卫不因 full-suite 项缺失或 pending 新增任何打回/失败终态（回归测试覆盖）
- [x] 3.4 单测（落 `tests/test_impl_selfcheck_model_probe.py`）覆盖：框架侧产物优先（结论不一致取产物）、指纹陈旧与存量无指纹字段回退自查值、双源皆无 pending、缺项零打回、写侧 stamp 字段落盘

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-impl-selfcheck-model-probe/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过
