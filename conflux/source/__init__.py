"""Source adapters — Git is the initial protocol, not permanent foundation."""

from conflux.source.adapter import SourceAdapter
from conflux.source.git_adapter import GitSourceAdapter

__all__ = ["SourceAdapter", "GitSourceAdapter"]
