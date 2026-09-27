"""agent-run 专用 env 键剔除口径（单一来源）。

多个 spawn claude 子进程的车道——蒸馏 run（core/knowledge）、自由会话
（core/dashboard/session_manager，D1.11）、一次性架构图生成
（core/dashboard/routes/architecture_routes）——都与 agent-run 无关，
MUST NOT 把 agent-run 专用上下文键带进子进程环境。此前该 frozenset 在
三个模块各复制一份、仅靠「口径同 SessionManager._BANNED_ENV_KEYS」注释
互指，新增隔离键时易只改一处形成静默口径分裂；现统一从本模块 import
同一 frozenset（语义说明保留于此）。
"""

AGENT_RUN_BANNED_ENV_KEYS = frozenset({
    "FENIX_RUN_PROJECT_ROOT",
    "FENIX_RUN_WORKTREE",
    "CLAUDE_CODE_ENABLE_TODO_TOOLS",
})
