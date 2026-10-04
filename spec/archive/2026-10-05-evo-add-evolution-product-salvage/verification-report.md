# 验证报告：evo-add-evolution-product-salvage

> ⚠️ 本报告由框架于 2026-09-26T18:41:44Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T18:41:43.793176+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.62M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| delivered-salvage-suite-green | 交付测试套件全绿：tests/test_evolution_product_salvage.py 覆盖五类抢救场景、_salvage_evolution_out 合并配方单元行为与 read_contract 文案分级，14 例全部通过。出处 tests/test_evolution_product_salvage.py:191-363（spec specs/evolution-run/spec.md 全部 Scenario） | pass | 0/7 | - |
| salvage-out-written-cli-fail-ingests | run 失败也先抢救再清理（正向）：子代理已写出完整可解析产物后 CLI 以非零码退出，run_evolution 仍读出产物按成功落地（success=True、items_ingested=1、error 空），条目落进 items.jsonl（产物先读后删、未被静默丢弃），并落 INFO 说明 CLI 退出异常。独立探针进程内装配最小 runner 替身驱动，不依赖交付测试文件。出处 core/agent_runner/maintenance_runs.py:810-904（spec Scenario「写完产物但 CLI 非零退出」） | pass | 0/5 | - |
| salvage-missing-out-parts-merged | 已写分片未及合并（正向）：产物缺失但 <out>.parts/ 有 2 个分片，run_evolution 按 sorted(glob) 合并配方恢复产物后读取，按成功落地（success=True、2 条落进 items.jsonl），残片目录被清理。出处 core/agent_runner/maintenance_runs.py:928-975 _salvage_evolution_out（spec Scenario「已写分片未及合并」） | pass | 0/5 | - |
| salvage-partial-recovery-no-watermark-advance | 部分恢复（异常→失败落地）：抢救恢复条目数（1）少于待分析条目数（3），整轮按失败落地（success=False）、错误标注「缺失 2 条」，已恢复条目仍落地（幂等去重由下轮补齐），水位文件 run 前后不变（水位推进由 fenixd worker 按 success 门控，见 fenixd.py:3532-3577，success=False 即 MUST NOT advance_watermark）。出处 core/agent_runner/maintenance_runs.py:850-858（spec Scenario「部分恢复不推进水位」） | pass | 0/5 | - |
| salvage-parts-count-match-succeeds | 恢复完整契约判定（对照场景）：恢复条目数（2）与待分析条目数（2）一致，CLI 非零退出仍按成功落地（success=True、2 条落地、error 空）——与部分恢复场景形成「条目数一致/不足」判定分叉的双向覆盖。出处 core/agent_runner/maintenance_runs.py:830-879（spec Scenario「已写分片未及合并」THEN 完整分支） | pass | 0/5 | - |
| salvage-unparsable-out-overwritten | 产物半写抢救（异常路径）：产物文件存在但 JSON 截断不可解析（增量合并覆盖写瞬间的半写窗口）且 .parts 有分片，_salvage_evolution_out 合并覆盖恢复后按成功落地，残片目录清理。出处 core/agent_runner/maintenance_runs.py:951-955（可解析检查失败才覆盖） | pass | 0/5 | - |
| salvage-nothing-savable-not-written | 确无产物可救（空状态）：产物缺失且 .parts 目录只有非 json 残片垃圾，抢救无可合并分片，按失败处理且错误文案为「产物文件未写出」，清理范围含 .parts 残片目录。出处 core/agent_runner/maintenance_runs.py:885-894 finally + core/evolution.py:1888-1891（spec Scenario「无产物可救」） | pass | 0/5 | - |
| salvage-empty-items-no-success-flip | 空契约不翻转成功（异常边界）：CLI 非零退出但产物可解析且 items 为空数组（无待分析条目、expected 未知），无从证明恢复出完整契约，不按成功翻转——success=False、错误文案「CLI 退出异常且契约产物无条目」。出处 core/agent_runner/maintenance_runs.py:859-879（空条目不翻转分支） | pass | 0/5 | - |
| salvage-helper-merge-recipe-unit | _salvage_evolution_out 合并配方单元行为（四组）：产物完整可解析时不覆盖（返回 None、产物原样）；分片目录缺失/只有非 json 时返回 None 且不产出产物；损坏分片（非法 JSON、非对象 JSON）逐片跳过不阻塞好分片恢复，run_id 从文件名复算、degraded 置 None；_delete_evolution_parts_dir 对已删/缺失目录幂等静默。出处 core/agent_runner/maintenance_runs.py:907-975 | pass | 0/5 | - |
| read-contract-message-split | 失败归因分级（回归点）：read_contract 对文件不存在报「产物文件未写出」、JSON 非法报「产物 JSON 不可解析」，两文案互不包含、告警与日志可直接判别失败面；既有契约校验文案（缺 items 数组）不随分级改动漂移。出处 core/evolution.py:1867-1900（spec Requirement「失败归因分级」Scenario「归因可分辨」） | pass | 0/5 | - |
| evolution-md-incremental-merge-contract | 分片增量合并契约落进提示词（静态取证）：agents/evolution.md 分片写入节含「增量合并；禁止最后一次性合并」指令、每写完一条分片立即执行并入脚本、任意中断点最大损失为单条分片的说明、结尾全量校验步保留；并入脚本与框架抢救配方同源（sorted(glob) 拼 items）且含 rm -rf 分片目录清理步。出处 agents/evolution.md:157-215（spec Requirement「分片增量合并契约」Scenario「中断点损失有界」） | pass | 0/5 | - |
| regression-self-evolution-suite | 回归：既有 evolution 相关测试 tests/test_self_evolution.py 全绿（成功路径行为不随抢救重排漂移，tasks 2.2 回归要求）。出处 tests/test_self_evolution.py（122 例，2026-09-27 实测基线） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

