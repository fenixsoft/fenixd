"""core.dashboard.routes — Dashboard 路由子包（refactor-giant-classes D1/D3/D5/D6）。

各组方法按资源拆分为 mixin，DashboardHandler 继承它们（D5：MRO 中
资源组须排在 BaseHTTPRequestHandler 之前）。server.py 从各子模块直接
导入 mixin；下方 __init__ 级 re-export 仅为包级导入便利/兼容保留，
并非完整门面——新增 mixin（如 H11+）时须在此同步追加。编号命名的
唯一例外是 session 组：H_SessionRoutesMixin 沿用引入时
（dashboard-live-session D3）的无编号类名，不占用 H 序号，在下方
列表与 server.py 的 MRO 中均位于 H10 与 H11 之间。
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
# [fenix-ignore:678ca6b82679] re-export 列表实际已按序登记 H15/H17（下方两行），与 docstring 同步纪律一致，条目所指缺失不存在
from .topology_routes import H15TopologyRoutesMixin
from .command_center_routes import H17CommandCenterRoutesMixin