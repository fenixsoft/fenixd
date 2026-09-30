"""core.dashboard.routes — Dashboard 路由子包（refactor-giant-classes D1/D3/D5/D6）。

各组方法按资源拆分为 mixin，DashboardHandler 继承它们（D5：MRO 中
资源组须排在 BaseHTTPRequestHandler 之前）。server.py 从各子模块直接
导入 mixin；下方 __init__ 级 re-export 仅为包级导入便利/兼容保留，
并非完整门面——新增 mixin（如 H11+）时须在此同步追加。
"""

from .base import H0BaseMixin
from .project_routes import H2ProjectRoutesMixin
from .spec_routes import H3SpecRoutesMixin
from .run_routes import H4RunRoutesMixin
from .settings_routes import H5SettingsRoutesMixin
from .alert_routes import H6AlertRoutesMixin
from .evolution_routes import H7EvolutionRoutesMixin
from .help_routes import H8HelpRoutesMixin
from .sse_routes import H9SseRoutesMixin
from .static_routes import H10StaticRoutesMixin
from .session_routes import H_SessionRoutesMixin
from .code_review_routes import H11CodeReviewRoutesMixin
from .regression_routes import H12RegressionRoutesMixin
from .architecture_routes import H13ArchitectureRoutesMixin
from .knowledge_routes import H14KnowledgeRoutesMixin