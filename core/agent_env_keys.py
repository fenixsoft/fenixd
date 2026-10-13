"""agent-run 专用 env 键剔除口径（单一来源）。

所有 spawn claude 子进程的非 agent-run 车道——蒸馏 run（core/knowledge）、
知识回填（core/knowledge_backfill）、自由会话
（core/dashboard/session_manager，D1.11）、一次性架构图生成
（core/dashboard/routes/architecture_routes）——都与 agent-run 无关，
MUST NOT 把 agent-run 专用上下文键带进子进程环境。消费方清单以
grep AGENT_RUN_BANNED_ENV_KEYS 的实测结果为准（此处枚举仅为快照，
新增车道时勿依赖本清单）。此前该 frozenset 在各消费车道模块内各自
复制一份、仅靠「口径同 SessionManager._BANNED_ENV_KEYS」注释互指，
新增隔离键时易只改一处形成静默口径分裂；现统一从本模块 import
同一 frozenset（语义说明保留于此）。
"""

AGENT_RUN_BANNED_ENV_KEYS = frozenset({
    "FENIX_RUN_PROJECT_ROOT",
    "FENIX_RUN_WORKTREE",
    "CLAUDE_CODE_ENABLE_TODO_TOOLS",
})

# ── dsh 通道防串扰剔除口径（add-dsh-adapter-integration 1.3）───────────────
# dsh 子进程（fenix-dsh-bundle 的 pi-ai 路由）凭据经 patch 的 apiKeyEnv 指名
# 变量（FENIX_DSH_PROVIDER_API_KEY）显式桥接，MUST NOT 依赖继承的
# ANTHROPIC_*/CLAUDE_* 键：残留的 ANTHROPIC_BASE_URL/API_KEY 会与 provider
# 链分配的端点串扰（dsh 按自己的配置渲染端点，继承键只会误导诊断）；残留的
# ANTHROPIC_AUTH_TOKEN 是 claude 认证语义，对 dsh 纯噪音。前缀集按显式枚举
# 收敛（ANTHROPIC_/CLAUDE_ 两族），不做宽泛 *KEY* 通配。
DSH_BANNED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_")

# 显式键：凭据桥接变量由 adapter 在剔除后注入（值来自 provider 链分配，而非
# daemon 进程继承值）；DSH_HOME 由工厂按 agent.dsh_home 配置注入，继承值
# 一律剔除（配置单一来源）。
DSH_BANNED_ENV_EXACT_KEYS = frozenset({
    "FENIX_DSH_PROVIDER_API_KEY",
    "DSH_HOME",
})


def dsh_banned_env_keys(env):
    """返回 env 中命中 dsh 防串扰剔除口径的键清单（DshAdapter.build_env 消费）。

    与 AGENT_RUN_BANNED_ENV_KEYS 的静态 frozenset 不同，dsh 口径含前缀匹配，
    需要对实际 env 求值；返回 list（确定性顺序：env 迭代序）。
    """
    return [
        key
        for key in env
        if key in DSH_BANNED_ENV_EXACT_KEYS
        or key.startswith(DSH_BANNED_ENV_PREFIXES)
    ]
