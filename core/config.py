"""
config.py — Configuration loader for fenixd.

Reads and validates config.yaml, providing typed access to all settings.
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class ConfigLoader:
    """Load and validate fenixd configuration from YAML."""

    # Required top-level keys
    REQUIRED_KEYS = ["project", "schedule", "agents", "worktree", "gates", "commands", "logging"]

    # Valid project types
    VALID_PROJECT_TYPES = ["web", "cli", "library", "api"]

    # Known agent types for model assignment
    KNOWN_AGENT_TYPES = ["implementer", "planner-plan", "planner-judge", "verifier"]

    # Valid approve modes
    VALID_APPROVE_MODES = ["manual", "auto"]

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

        # Validate llm.providers (optional — absence means empty registry)
        llm = config.get("llm") or {}
        if llm:
            cls._validate_llm(llm)

        # Validate agents.models (optional — absence means no assignments)
        agents = config.get("agents") or {}
        if "models" in agents and agents["models"]:
            cls._validate_agent_models(agents["models"], llm)

        # Validate gates.approve_mode (optional — defaults to manual)
        gates = config.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in cls.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {cls.VALID_APPROVE_MODES}: {mode}"
                )

    @classmethod
    def _validate_llm(cls, llm: Dict[str, Any]):
        providers = llm.get("providers")
        if providers is None:
            return
        if not isinstance(providers, list):
            raise ValueError(f"llm.providers must be a list, got: {type(providers).__name__}")

        seen_names = set()
        for idx, provider in enumerate(providers):
            if not isinstance(provider, dict):
                raise ValueError(f"llm.providers[{idx}] must be a dict")
            name = provider.get("name")
            baseurl = provider.get("baseurl")
            apikey = provider.get("apikey")
            if not name or not isinstance(name, str):
                raise ValueError(f"llm.providers[{idx}].name must be a non-empty string")
            if not baseurl or not isinstance(baseurl, str):
                raise ValueError(f"llm.providers[{idx}].baseurl must be a non-empty string")
            if not apikey or not isinstance(apikey, str):
                raise ValueError(f"llm.providers[{idx}].apikey must be a non-empty string")
            if name in seen_names:
                raise ValueError(f"llm.providers[{idx}].name must be unique: duplicate '{name}'")
            seen_names.add(name)

    @classmethod
    def _validate_agent_models(cls, models: Dict[str, Any], llm: Dict[str, Any]):
        if not isinstance(models, dict):
            raise ValueError(f"agents.models must be a dict, got: {type(models).__name__}")

        provider_names = set()
        providers = (llm or {}).get("providers") or []
        for p in providers:
            if isinstance(p, dict) and p.get("name"):
                provider_names.add(p["name"])

        for agent_type, assignment in models.items():
            if agent_type not in cls.KNOWN_AGENT_TYPES:
                raise ValueError(
                    f"agents.models key '{agent_type}' is not a known agent type. "
                    f"Known types: {cls.KNOWN_AGENT_TYPES}"
                )
            if not isinstance(assignment, dict):
                raise ValueError(f"agents.models.{agent_type} must be a dict")
            provider = assignment.get("provider")
            model = assignment.get("model")
            if not provider or not isinstance(provider, str):
                raise ValueError(f"agents.models.{agent_type}.provider must be a non-empty string")
            if provider not in provider_names:
                raise ValueError(
                    f"agents.models.{agent_type}.provider references unknown provider '{provider}'"
                )
            if not model or not isinstance(model, str):
                raise ValueError(f"agents.models.{agent_type}.model must be a non-empty string")

    @classmethod
    def get_agent_model_assignment(
        cls, config: Dict[str, Any], agent_type: str
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        """Return (provider_dict, model_name) for the given agent_type, or None if unassigned."""
        agents = config.get("agents") or {}
        models = agents.get("models") or {}
        assignment = models.get(agent_type)
        if not assignment:
            return None

        provider_name = assignment.get("provider")
        model = assignment.get("model")
        if not provider_name or not model:
            return None

        llm = config.get("llm") or {}
        providers = llm.get("providers") or []
        for p in providers:
            if isinstance(p, dict) and p.get("name") == provider_name:
                return (p, model)
        return None

    @classmethod
    def get_approve_mode(cls, config: Dict[str, Any]) -> str:
        """Return the approve_mode, defaulting to 'manual'."""
        gates = config.get("gates") or {}
        mode = gates.get("approve_mode")
        if mode not in cls.VALID_APPROVE_MODES:
            return "manual"
        return mode

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
