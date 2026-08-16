"""
event_bus.py — File-system event monitoring for fenixd.

Watches STATE.md for changes using inotify (Linux) and dispatches
internal events to the PM Engine. Includes periodic full-scan fallback.
"""

import hashlib
import threading
import time
from pathlib import Path
from typing import Dict, Set


class EventBus:
    """
    Monitor STATE.md for changes and dispatch events to PM Engine.

    Uses polling + checksum comparison for cross-platform compatibility
    (with optional inotify support on Linux).
    """

    def __init__(self, state_path: Path, state_machine, pm_engine, config, logger):
        self.state_path = Path(state_path)
        self.state_machine = state_machine
        self.pm_engine = pm_engine
        self.config = config
        self.logger = logger

        self._running = False
        self._watch_thread = None
        self._scan_thread = None
        self._last_checksum = None
        self._known_specs: Dict[str, str] = {}  # spec_name → status (last known)

    def start(self):
        """Start monitoring STATE.md for changes."""
        self._running = True

        # Record initial state
        self._update_known_state()

        # Start the inotify/polling watcher
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="fenixd-watcher",
            daemon=True,
        )
        self._watch_thread.start()
        self.logger.info("event_bus", "File watcher started")

        # Start periodic full scan
        poll_interval = self.config.get("schedule", {}).get("poll_interval_minutes", 30)
        self._scan_thread = threading.Thread(
            target=self._periodic_scan_loop,
            args=(poll_interval,),
            name="fenixd-scanner",
            daemon=True,
        )
        self._scan_thread.start()
        self.logger.info("event_bus", f"Periodic scanner started (interval: {poll_interval}m)")

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
        self.logger.info("event_bus", "Stopped")

    def full_scan(self):
        """Perform a complete scan of STATE.md, dispatch events, and run blocker check.
        Also recovers actionable states that may have been missed on daemon restart."""
        self.logger.debug("event_bus", "Performing full scan...")
        try:
            current_specs = self.state_machine.read_all()
            self._dispatch_changes(current_specs)

            # Recovery: explicitly re-trigger actionable states that may have been
            # missed due to daemon restart (known_specs already matches current state).
            # Skip specs that already completed their action to avoid re-trigger loops.
            for name, entry in current_specs.items():
                status = entry.get("status", "")
                if status == "drafted":
                    self.logger.info("event_bus", f"Recovery: re-triggering promote for '{name}'")
                    self.pm_engine.handle_event("spec_drafted", name, entry)
                elif status == "implemented":
                    # Skip if already had a tester run (already verified, avoid re-trigger loop)
                    if entry.get("tester_run"):
                        self.logger.debug("event_bus", f"Skipping recovery for '{name}': already verified")
                        continue
                    self.logger.info("event_bus", f"Recovery: re-triggering verify for '{name}'")
                    self.pm_engine.handle_event("spec_implemented", name, entry)
                elif status == "ready" and not entry.get("error"):
                    # Skip if already had an implementer run
                    if entry.get("implementer_run"):
                        self.logger.debug("event_bus", f"Skipping recovery for '{name}': already implemented")
                        continue
                    self.logger.info("event_bus", f"Recovery: re-triggering implement for '{name}'")
                    self.pm_engine.handle_event("spec_ready", name, entry)
                elif status == "bug-found":
                    self.logger.info("event_bus", f"Recovery: re-triggering bug_found for '{name}'")
                    self.pm_engine.handle_event("spec_bug_found", name, entry)
                elif status == "verified":
                    # Skip if already done (verified→done transition already happened)
                    self.logger.info("event_bus", f"Recovery: re-triggering verified→done for '{name}'")
                    self.pm_engine.handle_event("spec_verified", name, entry)

            # Run blocker detection as part of full scan
            self.pm_engine.check_blockers()
        except Exception as e:
            self.logger.error("event_bus", f"Full scan failed: {e}")

    # ── Internal ──────────────────────────────────────────────────

    def _watch_loop(self):
        """Poll STATE.md for changes using checksum comparison."""
        while self._running:
            try:
                if not self.state_path.exists():
                    time.sleep(2)
                    continue

                current_hash = self._file_checksum()
                if current_hash != self._last_checksum:
                    self._last_checksum = current_hash
                    self.logger.debug("event_bus", "STATE.md changed, dispatching...")
                    current_specs = self.state_machine.read_all()
                    self._dispatch_changes(current_specs)
            except Exception as e:
                self.logger.error("event_bus", f"Watch error: {e}")

            time.sleep(2)  # Poll every 2 seconds

    def _periodic_scan_loop(self, interval_minutes: int):
        """Periodic full scan as fallback."""
        while self._running:
            time.sleep(interval_minutes * 60)
            if self._running:
                self.logger.debug("event_bus", "Periodic scan triggered")
                self.full_scan()

    def _file_checksum(self) -> str:
        """Compute MD5 checksum of STATE.md."""
        if not self.state_path.exists():
            return ""
        try:
            content = self.state_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception:
            return ""

    def _update_known_state(self):
        """Update internal snapshot of known SPEC states."""
        specs = self.state_machine.read_all()
        self._known_specs = {
            name: entry.get("status", "drafted")
            for name, entry in specs.items()
        }

    def _dispatch_changes(self, current_specs: dict):
        """Compare current state against known state and dispatch events."""
        events = []

        # Check for new or changed SPECs
        for name, entry in current_specs.items():
            new_status = entry.get("status", "drafted")
            old_status = self._known_specs.get(name)

            if old_status is None:
                # New SPEC appeared — dispatch event based on its current status
                event_kind = EventBus._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))
            elif old_status != new_status:
                # Status changed
                event_kind = self._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))

        # Update known state
        self._known_specs = {
            name: entry.get("status", "drafted")
            for name, entry in current_specs.items()
        }

        # Dispatch events to PM Engine
        for event_kind, spec_name, spec_entry in events:
            self.logger.info(
                "event_bus",
                f"Event: {event_kind} for '{spec_name}'",
            )
            try:
                self.pm_engine.handle_event(event_kind, spec_name, spec_entry)
            except Exception as e:
                self.logger.error(
                    "event_bus",
                    f"PM Engine failed to handle {event_kind}: {e}",
                )

    @staticmethod
    def _status_to_event(status: str) -> str:
        """Map a SPEC status to an internal event type."""
        mapping = {
            "drafted": "spec_drafted",
            "ready": "spec_ready",
            "implemented": "spec_implemented",
            "verified": "spec_verified",
            "bug-found": "spec_bug_found",
            "done": "spec_done",
        }
        return mapping.get(status, "")
