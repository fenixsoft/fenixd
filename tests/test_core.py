"""
Unit tests for Fenix Loop Engineering Framework core modules.

This file is now a thin wrapper that imports from the split test modules.
The actual test implementations are in:
- test_state_machine.py
- test_config.py
- test_event_bus.py
- test_pm_dispatch.py
- test_pm_verification.py
- test_pm_recovery.py
- test_pm_budget.py
- test_pm_reporting.py
- test_runner_provider.py
- test_runner_prompt.py
- test_dashboard_data.py

Run with: python3 -m pytest tests/test_core.py -v
"""

# Import all test classes from the split modules
# This maintains backward compatibility while the actual tests are in the new modules

from tests.test_state_machine import (
    TestStateParser,
    TestStateParserHalfWriteDefense,
    TestStateMachine,
    TestSpecStatus,
    TestVerifiedTestingEscapeHatch,
    TestBlockedState,
)

from tests.test_config import (
    TestConfigLoader,
    TestDeepMerge,
    TestResolveConfig,
    TestConfigHotReload,
    TestLogger,
)

from tests.test_event_bus import (
    TestEventBus,
    TestEventBusFullScanResilience,
    TestEventBusReadyWhitelistRecovery,
)

from tests.test_pm_dispatch import (
    TestPMEngineBugFound,
    TestPMEngineBugFoundIdempotent,
    TestPMEngineSameStatusResetDispatch,
    TestRouteTableGuard,
    TestEngineRouteCrossCheck,
)

from tests.test_pm_verification import (
    TestVerifierStaleResultGuard,
    TestVerifierCircuitOpenHoldsState,
    TestVerifyEngineScreenshotTiming,
    TestUniformVerifyFailure,
    TestImplementerZeroChangeGuard,
    TestVerifierInfraFailureHold,
    TestJudgeEnvDeclaredGuard,
    TestEnsureAppReachableFieldFix,
    TestScenarioNavigateAcceptance,
    TestBrowserNavigateBackstop,
    TestVerificationCompletionGate,
    TestVerificationProgressGateD6,
    TestScenarioFreezeIntegration,
)

from tests.test_pm_recovery import (
    TestPMEngineReplanLoop,
    TestPMEngineMergeBackIntegration,
    TestMergeCircuitBreakerFingerprint,
    TestMainTreeHealthCheck,
    TestStashPopConflictSelfHeal,
    TestStuckThresholdUnify,
)

from tests.test_pm_budget import (
    TestCostControl,
)

from tests.test_pm_reporting import (
    TestPlannerResultReadback,
    TestPriorityScheduler,
    TestSpecSummaryCreatedUpdated,
    TestApiSpecsSortOrder,
)

from tests.test_runner_provider import (
    TestAgentRunnerModelRouting,
    TestAgentRunResult,
    TestRunClaudeStreaming,
    TestExecuteAgentAttemptRunId,
)

from tests.test_runner_prompt import (
    TestAutoApprove,
    TestRunClaudeCwd,
)

from tests.test_dashboard_data import (
    TestDashboardConfigIO,
    TestDashboardParallelismConfig,
    TestWorktreeMergeBack,
)


if __name__ == "__main__":
    import unittest
    unittest.main()
