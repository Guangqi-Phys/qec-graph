"""Optional model-provider integration for QEC Graph.

The package is intentionally import-safe: no provider is contacted and no
credentials are read until a command explicitly builds an AI request.
"""
from .config import AIConfig, AIConfigError, load_ai_config, render_config_template

__all__ = ['AIConfig', 'AIConfigError', 'load_ai_config', 'render_config_template']
