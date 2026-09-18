"""core.dashboard.routes — Dashboard 路由子包（refactor-giant-classes D1/D3/D5/D6）。

各组方法按资源拆分为 mixin，DashboardHandler 继承它们（D5：MRO 中
资源组须排在 BaseHTTPRequestHandler 之前）。门面 re-export 全部公开名。
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