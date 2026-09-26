# impl-result-gate：fast-track verification 段写后校验

## ADDED Requirements

### Requirement: fast-track success 结果文件必须在 run 末通过 verification 段校验
实现 run（fast-track 车道）结束时，产物硬门对 status 为 success 且 mode 为 fast-track 的结果文件执行 `parse_fast_track_verification`（core/fast_track_result.py:59）校验；解析失败即硬门失败，错误信息说明 verification 段缺失或结构不完整，run 不得以 success 收尾。

#### Scenario: 缺 verification 段的 success 结果在 run 末被拦截
- WHEN fast-track run 以 success 终态交付的结果文件顶层无合法 verification 段（scenarios 为空/缺失、verdict 非法等）
- THEN 产物硬门报错，run 进入既有产物门原地退避重试，实现者下一轮收到错误当场补写

#### Scenario: 补写后放行
- WHEN 实现者在重试轮补写合规 verification 段
- THEN 硬门通过，run 正常 success 收尾，dispatch 交接点不再因此拒收

### Requirement: 诚实退出与 full 车道不受影响
partial/error 状态的 fast-track 结果文件不触发该校验（本就不含 verification 段）；mode 非 fast-track 的结果文件不触发该校验。

#### Scenario: 诚实退出不误拦
- WHEN fast-track run 以 partial/error 诚实退出交付结果文件
- THEN 产物硬门不因 verification 段缺失而失败

#### Scenario: full 车道不误拦
- WHEN full 车道实现 run 交付不含 mode==fast-track 的结果文件
- THEN 产物硬门行为与现状完全一致

### Requirement: 注入契约与硬门同频
fast-track 车道运行时注入的结果文件契约段必须声明：success 结果文件必须含合法 verification 段（scenarios 非空、每条含非空 scenario_id/description、status 枚举合法、verdict 属 verified/bug-found）。

#### Scenario: 契约段声明 verification 要求
- WHEN fast-track run 启动、注入结果文件契约
- THEN 契约文本包含 verification 段结构要求，与 run 末校验同一解析器口径