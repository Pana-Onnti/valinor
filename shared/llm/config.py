"""
Configuration system for LLM providers with feature flag support.
Allows runtime switching between providers without code changes.
"""

import os
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import json
from pathlib import Path


class ProviderType(str, Enum):
    """Available LLM provider types"""
    ANTHROPIC_API = "anthropic_api"
    CONSOLE_CLI = "console_cli"   # Local claude CLI (Plan Max, no API key needed)
    MOCK = "mock"                 # For testing
    

class FeatureFlagSource(str, Enum):
    """Where to read feature flags from"""
    ENV = "environment"
    FILE = "file"
    REDIS = "redis"
    API = "api"


@dataclass
class LLMConfig:
    """
    Master configuration for LLM provider switching.
    Supports multiple configuration sources and runtime switching.
    """
    
    # Primary configuration
    provider_type: ProviderType = ProviderType.ANTHROPIC_API
    feature_flag_source: FeatureFlagSource = FeatureFlagSource.ENV
    
    # Provider-specific configs
    anthropic_config: Dict[str, Any] = field(default_factory=dict)
    cli_config: Dict[str, Any] = field(default_factory=dict)
    
    # Feature flags
    enable_fallback: bool = True
    fallback_provider: Optional[ProviderType] = ProviderType.MOCK  # Changed default
    enable_caching: bool = True
    enable_monitoring: bool = True
    enable_cost_tracking: bool = True
    
    # Runtime overrides
    force_provider: Optional[ProviderType] = None
    dry_run: bool = False
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load configuration from environment variables"""
        provider = os.getenv("LLM_PROVIDER", ProviderType.CONSOLE_CLI.value)
        
        config = cls(
            provider_type=ProviderType(provider),
            feature_flag_source=FeatureFlagSource(
                os.getenv("FEATURE_FLAG_SOURCE", FeatureFlagSource.ENV.value)
            ),
            anthropic_config={
                "api_key": os.getenv("ANTHROPIC_API_KEY"),
                "base_url": os.getenv("ANTHROPIC_BASE_URL"),
                "timeout": int(os.getenv("ANTHROPIC_TIMEOUT", "300")),
                "max_retries": int(os.getenv("ANTHROPIC_MAX_RETRIES", "3"))
            },
            cli_config={
                "cli_path": os.getenv("CLAUDE_CLI_PATH", "claude"),
                "timeout": int(os.getenv("CLAUDE_CLI_TIMEOUT", "300")),
            },
            console_config={
                "username": os.getenv("CLAUDE_USERNAME"),
                "password": os.getenv("CLAUDE_PASSWORD"),  # Should use secure storage
                "session_file": os.getenv("CLAUDE_SESSION_FILE", "/tmp/.claude_session"),
                "headless": os.getenv("CLAUDE_HEADLESS", "true").lower() == "true",
                "proxy": os.getenv("CLAUDE_PROXY")
            },
            enable_fallback=os.getenv("LLM_ENABLE_FALLBACK", "true").lower() == "true",
            fallback_provider=ProviderType(os.getenv("LLM_FALLBACK_PROVIDER", ProviderType.ANTHROPIC_API.value)) if os.getenv("LLM_FALLBACK_PROVIDER") else None,
            enable_caching=os.getenv("LLM_ENABLE_CACHING", "true").lower() == "true",
            enable_monitoring=os.getenv("LLM_ENABLE_MONITORING", "true").lower() == "true",
            enable_cost_tracking=os.getenv("LLM_ENABLE_COST_TRACKING", "true").lower() == "true",
            force_provider=ProviderType(os.getenv("LLM_FORCE_PROVIDER")) if os.getenv("LLM_FORCE_PROVIDER") else None,
            dry_run=os.getenv("LLM_DRY_RUN", "false").lower() == "true"
        )
        
        return config
    
    @classmethod
    def from_file(cls, filepath: str) -> "LLMConfig":
        """Load configuration from JSON/YAML file"""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")
        
        with open(path) as f:
            data = json.load(f)
        
        return cls(
            provider_type=ProviderType(data.get("provider", ProviderType.ANTHROPIC_API.value)),
            feature_flag_source=FeatureFlagSource(data.get("feature_flag_source", FeatureFlagSource.FILE.value)),
            anthropic_config=data.get("anthropic", {}),
            console_config=data.get("console", {}),
            enable_fallback=data.get("enable_fallback", True),
            fallback_provider=ProviderType(data["fallback_provider"]) if data.get("fallback_provider") else None,
            enable_caching=data.get("enable_caching", True),
            enable_monitoring=data.get("enable_monitoring", True),
            enable_cost_tracking=data.get("enable_cost_tracking", True),
            force_provider=ProviderType(data["force_provider"]) if data.get("force_provider") else None,
            dry_run=data.get("dry_run", False)
        )
    
    def get_active_provider(self) -> ProviderType:
        """Get the currently active provider based on flags and overrides"""
        if self.force_provider:
            return self.force_provider
        
        # Check feature flag source for dynamic switching
        if self.feature_flag_source == FeatureFlagSource.ENV:
            dynamic_provider = os.getenv("LLM_DYNAMIC_PROVIDER")
            if dynamic_provider:
                try:
                    return ProviderType(dynamic_provider)
                except ValueError:
                    pass
        
        return self.provider_type
    
    def get_provider_config(self, provider_type: Optional[ProviderType] = None) -> Dict[str, Any]:
        """Get configuration for a specific provider"""
        provider = provider_type or self.get_active_provider()
        
        if provider == ProviderType.ANTHROPIC_API:
            return self.anthropic_config
        elif provider == ProviderType.CONSOLE_CLI:
            return self.cli_config
        else:
            return {}
    
    def should_use_fallback(self, primary_error: Optional[Exception] = None) -> bool:
        """Determine if fallback should be used based on error and config"""
        if not self.enable_fallback or not self.fallback_provider:
            return False
        
        if primary_error:
            # Implement smart fallback logic based on error type
            error_msg = str(primary_error).lower()
            fallback_triggers = [
                "rate limit",
                "quota exceeded", 
                "authentication failed",
                "timeout",
                "connection error"
            ]
            return any(trigger in error_msg for trigger in fallback_triggers)
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        return {
            "provider": self.provider_type.value,
            "feature_flag_source": self.feature_flag_source.value,
            "anthropic": self.anthropic_config,
            "console": self.console_config,
            "enable_fallback": self.enable_fallback,
            "fallback_provider": self.fallback_provider.value if self.fallback_provider else None,
            "enable_caching": self.enable_caching,
            "enable_monitoring": self.enable_monitoring,
            "enable_cost_tracking": self.enable_cost_tracking,
            "force_provider": self.force_provider.value if self.force_provider else None,
            "dry_run": self.dry_run
        }