"""Draft raw CTF challenges into Droplet/XBOW-like dataset structure."""

from .agent import AgentSuggestion, LLMConfig
from .generator import PreprocessResult, generate_draft

__all__ = ["AgentSuggestion", "LLMConfig", "PreprocessResult", "generate_draft"]
