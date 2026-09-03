"""core/agent_runner — Agent 执行引擎包（refactor-core-packages）。

由单文件 agent_runner.py 重组为「门面 + 职责组件」结构（design D2）：

- runner.py            AgentRunner 门面：_execute_agent/_run_claude 留此，组装
                       组件，为测试引用的私有方法保留一行委托（design D3 规则 4）
- prompt_builder.py    PromptBuilder：提示词构建（准纯函数，阶段 1）
- provider_circuit.py  ProviderCircuit：熔断/切换冷却/当日计数（阶段 2）
- token_budget.py      TokenAccountant：用量累计/预算告警（阶段 2）
- v2_server.py         V2ServerManager：per-run 隔离测试服务（阶段 2）
- run_files.py         运行产物模块级函数（阶段 2）
- liveness.py          LivenessSupervisor：存活探测/判活/超时监督（阶段 3）
- session.py           SessionTracker：session id 与 usage 提取（阶段 3）

对外 API 兼容保证（spec core-package-structure「外部 API 零变化」）：
`fenixd.py` 的 `from core.agent_runner import AgentRunner`、
`core/dashboard/data.py` 的 `from core.agent_runner.run_files import run_spec_part`、
测试的常量导入与 `agent_runner_module.subprocess` 这类模块属性补丁缝隙
全部保持可用。核心导出显式列出，其余经 `from .runner import *` 转导。
"""

from .runner import (  # noqa: F401
    AdminDisposition,
    AgentRunResult,
    AgentRunner,
    archive_spec_runs,
    run_spec_part,
)
from .runner import *  # noqa: F401,F403
