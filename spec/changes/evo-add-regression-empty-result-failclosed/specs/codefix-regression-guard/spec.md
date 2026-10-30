# 能力规格：codefix-regression-guard

## 需求

### R1 空结果 fail-closed

WHEN 定向回归命令退出码非 0 且解析所得 JUnit XML 用例总数为 0 时，系统 SHALL 按 parse_error/infra 失败处理，MUST NOT 判 passed。

### R2 结果新鲜度

WHEN 拟据 JUnit XML 判 passed 且该文件 mtime 早于本次命令 started_at 时，系统 SHALL 按 R1 同类失败处理，MUST NOT 采信陈旧结果。

### R3 定向 targets 消毒

WHEN 构造定向回归目标列表时，系统 SHALL 过滤 # 前缀项、__pycache__ 路径与不存在路径，并 SHALL 对被过滤项留 WARNING 痕（含过滤原因）。

### R4 哨兵残留消除

WHEN 替换声明中的 {test_targets} 占位时，系统 SHALL 保证哨兵符号 # 不残留进最终执行命令。

## 行为约束

- targets 合法时的判定行为、批次吞吐、salvage 语义均不变。
- fail-closed 触发时按既有 parse_error/infra 失败链路处置（含留痕与批次收尾语义），不新增告警通道。
