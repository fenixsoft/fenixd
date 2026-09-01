# Design: fix-startup-double-dispatch

## Overview

This design addresses the startup double-dispatch race condition in the Fenix daemon where the same spec can be dispatched to two implementers during startup. The solution involves three main components:

1. **Dispatch Single-Flight Guard**: Prevent duplicate dispatches for the same spec during startup
2. **State Writeback Protection**: Prevent merge-back failures from overwriting active testing states  
3. **Verifier Final State Reconciliation**: Ensure verification results are never lost regardless of state races

## Technical Approach

### 1. Dispatch Single-Flight Guard

**Problem**: During daemon startup, two dispatch paths (startup scan + event replay) can both pass the existing guard (`has_active_worktree`) before the first run registers a worktree lock.

**Solution**: Implement an in-process dispatch registry that tracks specs with pending dispatches:

```python
# In core/pm_engine/engine.py
class PMEngine:
    def __init__(self):
        self._pending_dispatches: set = set()  # spec names with pending dispatches
        
    def _on_spec_ready(self, spec_name: str):
        # 派发单飞守卫（fix-startup-double-dispatch）：原子检查是否已在派发中
        if spec_name in self._pending_dispatches:
            self.logger.debug(f"Skipping duplicate dispatch for {spec_name}: already pending")
            return
            
        # 标记为正在派发（在任何异步操作之前）
        self._pending_dispatches.add(spec_name)
        
        try:
            # Existing dispatch logic
            ...
        finally:
            # 派发完成（成功或失败），从 pending 中移除，允许未来派发
            self._pending_dispatches.discard(spec_name)
```

**Key Points**:
- Uses in-process set for atomicity (no file I/O races)
- Guard is set **before** worktree lock creation (封死启动窗口)
- Clears after dispatch completes (success or failure)
- Handles concurrent async calls correctly via Python GIL

### 2. State Writeback Protection

**Problem**: Merge-back failures can overwrite active testing states with `ready`, causing verification results to be lost.

**Solution**: Add pre-checks before state writebacks in `_run_agent_worker`:

```python
# In core/pm_engine/dispatch.py - implementer completion handler
if not merge_ok:
    # 状态回写保护（fix-startup-double-dispatch）：
    # merge-back 失败回写 ready 前，检查 spec 当前状态——若已在
    # testing/implemented 且存在活跃 tester run，不降级 ready，
    # 只记录冲突并待验证结束后统一处置（避免覆写在飞验证态）。
    current_status = (spec_entry or {}).get("status", "")
    active_tester = (spec_entry or {}).get("tester_run")
    if current_status in ("testing", "implemented") and active_tester:
        self._pm.logger.warning(
            f"Merge-back failed for '{spec_name}' but spec is in "
            f"'{current_status}' with active tester run {active_tester} "
            f"— not downgrading to ready, conflict logged",
        )
        # 记录冲突但不降级状态，保持 testing/implemented
        self._pm.state_machine.update_spec(spec_name, {
            "error": final_error,
            "_merge_fp": fp,
            "_merge_streak": streak,
        })
        return
```

### 3. Verifier Final State Reconciliation

**Problem**: Verifier completion can be lost if spec state was changed by race conditions.

**Solution**: Implement reconciliation logic in `_run_legacy_verification`:

```python
# In core/pm_engine/verification.py
if verifier_status == "bug-found":
    # Verifier final state reconciliation (fix-startup-double-dispatch):
    # If spec state is not "testing" due to race conditions, reconcile
    current_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
    if current_status != "testing":
        # State changed by race condition - reconcile
        if current_status == "implemented":
            # Verification passed and implementation merged - replay legal path
            self._pm.logger.info(
                f"Reconciling '{spec_name}': verification found bugs, "
                f"but spec is in '{current_status}' - replaying to bug-found",
            )
            # Replay: implemented → testing → bug-found
            if self._pm.state_machine.is_valid_transition(current_status, "testing"):
                self._pm.state_machine.transition(spec_name, "testing")
                self._pm.state_machine.transition(spec_name, "bug-found")
            else:
                # Cannot transition - block with evidence
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "blocked",
                    "error": f"Verification found bugs but cannot reconcile state "
                             f"from '{current_status}': {result.error}",
                })
                return
        else:
            # Other state - block with evidence
            self._pm.state_machine.update_spec(spec_name, {
                "status": "blocked",
                "error": f"Verification found bugs but spec is in unexpected state "
                         f"'{current_status}': {result.error}",
            })
            return
```

## Implementation Details

### Files Modified

1. **`core/pm_engine/engine.py`**:
   - Added `_pending_dispatches` set to `PMEngine.__init__`
   - Modified `_on_spec_ready` to implement single-flight guard with atomic check
   - Added logging for debugging single-flight guard behavior

2. **`core/pm_engine/dispatch.py`**:
   - Modified `_run_agent_worker` to add state writeback protection
   - Added check for active tester run before downgrading to ready
   - Added conflict logging when merge-back fails during active testing

3. **`core/pm_engine/verification.py`**:
   - Modified `_run_legacy_verification` to add verifier final state reconciliation
   - Added logic to replay legal transition path when state changed during verification
   - Added blocking with evidence when verification fails or implementation not merged

### Testing Strategy

1. **Unit Tests** (`tests/test_startup_double_dispatch.py`):
   - `TestSingleFlightGuard`: Tests single-flight guard with concurrent and sequential dispatches
   - `TestStateWritebackProtection`: Tests state writeback protection with active tester
   - `TestVerifierReconciliation`: Tests verifier reconciliation with various state scenarios

2. **Integration Tests**:
   - `TestStartupDuplicateDispatch`: Simulates startup with duplicate spec_ready events
   - `TestMergeBackFailureDuringActiveTesting`: Tests merge-back failure during active testing
   - `TestVerifierCompletionWithStateChanges`: Tests verifier completion with state changes

3. **Acceptance Criteria Validation**:
   - Verify only one implementer runs per spec during startup (test_single_flight_guard_prevents_concurrent_dispatch)
   - Verify merge-back failures don't overwrite active testing (test_merge_back_failure_preserves_testing_state_with_active_tester)
   - Verify verification results are never lost (test_verifier_reconciliation_when_state_changed_to_implemented)

## Risk Assessment

1. **Low Risk**: Single-flight guard uses in-process state, no external dependencies
2. **Low Risk**: State writeback protection adds minimal complexity to error handling
3. **Low Risk**: Verifier reconciliation uses existing state machine transition logic

## Migration Plan

1. Changes deployed as part of normal daemon restart
2. Comprehensive logging added for debugging
3. Existing test suite extended with new tests
4. No feature flags required - changes are backward compatible

## Success Metrics

1. **Primary**: Elimination of duplicate implementer runs for same spec
2. **Secondary**: Reduction in wasted implementation tokens
3. **Tertiary**: No verification results lost due to state races