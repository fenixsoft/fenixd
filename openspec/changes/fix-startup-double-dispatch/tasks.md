## 1. Dispatch Single-Flight Guard Implementation

- [x] 1.1 Add `_pending_dispatches` set to `PMEngine.__init__` to track specs with pending dispatches
- [x] 1.2 Modify `_on_spec_ready` to implement atomic single-flight check using `_pending_dispatches`
- [x] 1.3 Ensure dispatch guard is set before worktree lock creation to封死启动窗口
- [x] 1.4 Add proper cleanup in finally block to remove spec from `_pending_dispatches` after dispatch completes

## 2. State Writeback Protection Implementation

- [x] 2.1 Modify `_handle_implementer_completion` to check current state before merge-back failure writeback
- [x] 2.2 Add logic to detect active tester run when spec is in "testing" state
- [x] 2.3 Implement conflict logging when merge-back fails during active testing
- [x] 2.4 Ensure state is not downgraded to "ready" when active tester exists

## 3. Verifier Final State Reconciliation Implementation

- [x] 3.1 Modify `_handle_verifier_completion` to check if spec state is still "testing"
- [x] 3.2 Implement reconciliation logic for verification passed with implementation merged
- [x] 3.3 Add logic to replay legal transition path (implemented → testing → verified → done)
- [x] 3.4 Implement blocking with evidence when verification fails or implementation not merged

## 4. Testing and Validation

- [x] 4.1 Add unit tests for single-flight guard with concurrent dispatch attempts
- [x] 4.2 Add unit tests for state writeback protection with active tester
- [x] 4.3 Add unit tests for verifier reconciliation with various state scenarios
- [x] 4.4 Add integration tests simulating startup with duplicate spec_ready events
- [x] 4.5 Add integration tests for merge-back failure during active testing
- [x] 4.6 Add integration tests for verifier completion with state changes
- [x] 4.7 Run existing test suite to ensure no regressions

## 5. Documentation and Finalization

- [x] 5.1 Update design.md with implementation details
- [x] 5.2 Add logging for debugging single-flight guard behavior
- [x] 5.3 Verify acceptance criteria: only one implementer per spec during startup
- [x] 5.4 Verify acceptance criteria: merge-back failures don't overwrite active testing
- [x] 5.5 Verify acceptance criteria: verification results are never lost