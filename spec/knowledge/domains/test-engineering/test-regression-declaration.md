<!-- knowledge: capability=test-regression-declaration rev=1 sources=spec/archive/2026-09-25-add-test-regression-tab -->

# 全量回归声明（verify.yaml regression 段）

项目在 `.fenix/verify.yaml` 顶层 `regression` 段声明全量回归如何执行与结果如何解析，框架仅按声明消费、不假设项目技术栈。

## 现行规则

- `regression` 段为可选顶层段，字段：`cmd`（必填，字符串或 argv 列表，cwd 为项目根，命令须产出 JUnit XML 结果文件）；`output`（必填，JUnit XML 文件路径，相对项目根）；`timeout_seconds`（可选正整数，缺省 1800，硬超时）；`format`（可选，固定 `junit`，缺省 `junit`，本次仅支持 JUnit XML）；`long_test_threshold_seconds`（可选正数，缺省 10，长耗时用例阈值）。
- 段缺省不存在时按「未配置全量回归」处理：不报错、不派发，项目页「测试回归」分面显示引导态。
- 结构校验：`cmd` 与 `output` 缺失时该段视为无效，视同「未配置」回退处理并记 WARNING，不得因无效段导致 daemon 启动失败。
- 验证契约自动起草流程（add-verify-contract-autodraft 通道）一并起草 `regression` 段：`verify.yaml` 无该段（或文件缺失）时，administrator agent 识别项目测试体系（语言、测试框架、测试目录、运行命令），生成能产出 JUnit XML 的 `cmd` 与对应 `output`，并据实测设定合理 `timeout_seconds`。
- 起草产物经 `bin/fenix_verify_contract.py <项目根>` 三段自证（prepare/serve/ready）全通才落盘；`regression` 段自证为独立可选校验——段存在时按 `cmd` 跑一次确认 `output` 产出可解析 JUnit XML，其失败以省略该段收尾，且不得改变三段自证的退出码与判定语义（回归可跑 1800s，不得把既有自证门拖成小时级）。
- 探测失败（项目无测试体系、命令产不出 JUnit XML）以省略该段收尾，不臆造无效命令。
- 结果解析只认 JUnit XML（`testsuites`/`testsuite`/`testcase` 结构，`testcase` 带 `time` 属性，失败带 `failure`/`error`，跳过带 `skipped`）；框架不假设被测项目用 Python/pytest，命令形态、测试目录、测试数量均由项目声明。

## 溯源

- 2026-09-25 add-test-regression-tab — 新增 verify.yaml regression 段声明契约（字段与缺省、无效段回退、自动起草与独立可选自证、JUnit XML 单一解析口径）
