"""
config.py — Configuration loader for fenixd.

Reads and validates config.yaml, providing typed access to all settings.
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict


class ConfigLoader:
    """Load and validate fenixd configuration from YAML."""

    # Required top-level keys
    REQUIRED_KEYS = ["project", "schedule", "agents", "worktree", "gates", "commands", "logging"]

    # Valid project types
    VALID_PROJECT_TYPES = ["web", "cli", "library", "api"]

    @classmethod
    def load(cls, config_path: Path) -> Dict[str, Any]:
        """Load config from path, validate, and return as dict."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if config is None:
            raise ValueError(f"Config file is empty: {config_path}")

        cls._validate(config)
        return config

    @classmethod
    def _validate(cls, config: Dict[str, Any]):
        """Validate configuration structure and values."""
        # Check required keys
        for key in cls.REQUIRED_KEYS:
            if key not in config:
                raise ValueError(f"Missing required config key: '{key}'")

        # Validate schedule
        schedule = config["schedule"]
        poll = schedule.get("poll_interval_minutes", 30)
        if not isinstance(poll, (int, float)) or poll <= 0:
            raise ValueError(f"schedule.poll_interval_minutes must be positive: {poll}")

        # Validate agents
        agents = config["agents"]
        for field in ["max_concurrent", "max_retries", "max_turns"]:
            if not isinstance(agents.get(field, 0), int) or agents[field] <= 0:
                raise ValueError(f"agents.{field} must be a positive integer: {agents.get(field)}")

        # Validate project type
        ptype = config["project"].get("type", "")
        if ptype not in cls.VALID_PROJECT_TYPES:
            raise ValueError(
                f"project.type must be one of {cls.VALID_PROJECT_TYPES}: {ptype}"
            )

    @classmethod
    def get(cls, config: Dict[str, Any], dotted_key: str, default=None):
        """
        Get a nested config value by dotted key.
        E.g., config_get(config, "agents.max_turns", 50)
        """
        keys = dotted_key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value
