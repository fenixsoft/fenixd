"""
Dashboard 模块测试（add-fenix-dashboard 阶段 B/C：dashboard-server + dashboard-ui 数据层）。

This file is now a thin wrapper that imports from the split test modules.
The actual test implementations are in:
- test_dashboard_api.py (server API tests)
- test_dashboard_data.py (data parsing tests)
- test_dashboard_watcher.py (file watcher and SSE tests)

Run with: python3 -m pytest tests/test_dashboard.py -v
"""

# Import all test classes from the split modules
# This maintains backward compatibility while the actual tests are in the new modules

from tests.test_dashboard_api import (
    TestServerAPI,
    TestProjectLifecycleAPI,
)

from tests.test_dashboard_data import (
    TestDashboardConfigIO,
    TestDashboardParallelismConfig,
    TestWorktreeMergeBack,
)

from tests.test_dashboard_watcher import (
    TestFileWatcher,
    TestSSEHub,
)

# Import fixtures for backward compatibility
from tests.test_dashboard_api import server_fx

# Import make_project for backward compatibility
from tests.test_dashboard_api import make_project
