"""Source adapter interface.

Adapters are replaceable without changing project, build, release,
or deployment interfaces. Future native Conflux source storage
implements the same contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from conflux.models.project import SourceRef
from conflux.models.source import SourceRevision, SourceSnapshot


class SourceAdapter(ABC):
    """Contract for source-control backends."""

    kind: str = "abstract"

    @abstractmethod
    def inspect_branches(self, source: SourceRef) -> List[str]:
        """List branch names."""
        ...

    @abstractmethod
    def inspect_tags(self, source: SourceRef) -> List[str]:
        """List tag names."""
        ...

    @abstractmethod
    def resolve_revision(
        self,
        source: SourceRef,
        *,
        project_id: str,
        ref: str = "HEAD",
    ) -> Optional[SourceRevision]:
        """Resolve a ref to a SourceRevision."""
        ...

    @abstractmethod
    def list_revisions(
        self,
        source: SourceRef,
        *,
        project_id: str,
        branch: str = "",
        limit: int = 20,
    ) -> List[SourceRevision]:
        """Recent revisions on a branch."""
        ...

    @abstractmethod
    def snapshot(
        self,
        source: SourceRef,
        revision: SourceRevision,
    ) -> SourceSnapshot:
        """Create an immutable snapshot identity for a revision."""
        ...

    @abstractmethod
    def integrity_check(self, source: SourceRef) -> dict:
        """Basic repository integrity / reachability check."""
        ...
