"""core/agent_runner — Agent 执行引擎包（refactor-core-packages）。

由单文件 agent_runner.py 重组为「门面 + 职责组件」结构（design D2）：

- runner.py          AgentRunner 门面：_execute_agent/_run_claude 留此，组装组件，
                     为测试引用的私有方法保留一行委托（design D3 规则 4）
- prompt_builder.py  PromptBuilder：提示词构建（准纯函数，阶段 1）
- （后续阶段：provider_circuit / token_budget / v2_server / liveness /
   session / run_files 组件渐次就位）

对外 API 兼容保证（spec core-package-structure「外部 API 零变化」）：本包
`__init__` 从 runner 转导全部既有模块级名字（类、函数、常量），`fenixd.py`
的 `from core.agent_runner import AgentRunner`、`core/dashboard/data.py` 的
`from core.agent_runner import clean_old_runs`、测试的常量导入与
`agent_runner_module.subprocess` 这类模块属性补丁缝隙全部保持可用。
"""

from .runner import *  # noqa: F401,F403
