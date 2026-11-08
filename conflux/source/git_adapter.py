"""Git source adapter.

Uses existing Git tooling. Does not rewrite history or overwrite repos.
Object identities remain Git-compatible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from conflux.models.project import SourceRef
from conflux.models.source import SourceRevision, SourceSnapshot
from conflux.source.adapter import SourceAdapter

logger = logging.getLogger("conflux.git")


def _run_git(args: List[str], *, cwd: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class GitSourceAdapter(SourceAdapter):
    kind = "git"

    def _repo_path(self, source: SourceRef) -> Optional[str]:
        if source.local_path and Path(source.local_path).is_dir():
            git_dir = Path(source.local_path) / ".git"
            if git_dir.exists() or (Path(source.local_path) / "HEAD").exists():
                return source.local_path
        return None

    def inspect_branches(self, source: SourceRef) -> List[str]:
        path = self._repo_path(source)
        if not path:
            return [source.default_branch or "main"]
        r = _run_git(["branch", "--format=%(refname:short)"], cwd=path)
        if r.returncode != 0:
            return [source.default_branch or "main"]
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    def inspect_tags(self, source: SourceRef) -> List[str]:
        path = self._repo_path(source)
        if not path:
            return []
        r = _run_git(["tag", "--list"], cwd=path)
        if r.returncode != 0:
            return []
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    def resolve_revision(
        self,
        source: SourceRef,
        *,
        project_id: str,
        ref: str = "HEAD",
    ) -> Optional[SourceRevision]:
        path = self._repo_path(source)
        if not path:
            # Synthetic revision for remote-only registration (no local clone)
            synthetic = hashlib.sha256(f"{source.source_id}:{ref}".encode()).hexdigest()[:40]
            return SourceRevision(
                revision_id=synthetic,
                source_id=source.source_id,
                project_id=project_id,
                kind="git",
                branch=ref if ref != "HEAD" else (source.default_branch or "main"),
                message=f"unresolved remote ref {ref}",
                committed_at=time.time(),
            )
        r = _run_git(
            ["log", "-1", "--format=%H%n%P%n%an%n%at%n%s", ref],
            cwd=path,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        lines = r.stdout.strip().splitlines()
        sha = lines[0].strip()
        parents = lines[1].split() if len(lines) > 1 and lines[1].strip() else []
        author = lines[2].strip() if len(lines) > 2 else ""
        try:
            committed_at = float(lines[3]) if len(lines) > 3 else time.time()
        except ValueError:
            committed_at = time.time()
        message = lines[4] if len(lines) > 4 else ""
        tree_r = _run_git(["rev-parse", f"{sha}^{{tree}}"], cwd=path)
        tree_hash = tree_r.stdout.strip() if tree_r.returncode == 0 else ""
        return SourceRevision(
            revision_id=sha,
            source_id=source.source_id,
            project_id=project_id,
            kind="git",
            branch=ref if ref not in ("HEAD", sha) else "",
            message=message,
            author=author,
            committed_at=committed_at,
            parent_ids=parents,
            tree_hash=tree_hash,
        )

    def list_revisions(
        self,
        source: SourceRef,
        *,
        project_id: str,
        branch: str = "",
        limit: int = 20,
    ) -> List[SourceRevision]:
        path = self._repo_path(source)
        if not path:
            rev = self.resolve_revision(source, project_id=project_id, ref=branch or "HEAD")
            return [rev] if rev else []
        ref = branch or "HEAD"
        r = _run_git(
            ["log", f"-{limit}", "--format=%H%n%P%n%an%n%at%n%s%n---", ref],
            cwd=path,
        )
        if r.returncode != 0:
            return []
        out: List[SourceRevision] = []
        chunks = r.stdout.strip().split("---")
        for chunk in chunks:
            lines = [ln for ln in chunk.strip().splitlines() if ln.strip()]
            if len(lines) < 1:
                continue
            sha = lines[0].strip()
            parents = lines[1].split() if len(lines) > 1 and lines[1].strip() else []
            author = lines[2].strip() if len(lines) > 2 else ""
            try:
                committed_at = float(lines[3]) if len(lines) > 3 else 0.0
            except ValueError:
                committed_at = 0.0
            message = lines[4] if len(lines) > 4 else ""
            out.append(
                SourceRevision(
                    revision_id=sha,
                    source_id=source.source_id,
                    project_id=project_id,
                    kind="git",
                    branch=branch,
                    message=message,
                    author=author,
                    committed_at=committed_at,
                    parent_ids=parents,
                )
            )
        return out

    def snapshot(self, source: SourceRef, revision: SourceRevision) -> SourceSnapshot:
        path = self._repo_path(source)
        file_count = 0
        content_hash = revision.tree_hash or revision.revision_id
        if path:
            r = _run_git(["ls-tree", "-r", "--name-only", revision.revision_id], cwd=path)
            if r.returncode == 0:
                file_count = len([ln for ln in r.stdout.splitlines() if ln.strip()])
        snap_id = "snap_" + hashlib.sha256(
            f"{revision.revision_id}:{content_hash}".encode()
        ).hexdigest()[:16]
        return SourceSnapshot(
            snapshot_id=snap_id,
            revision_id=revision.revision_id,
            source_id=source.source_id,
            project_id=revision.project_id,
            file_count=file_count,
            content_hash=content_hash,
        )

    def integrity_check(self, source: SourceRef) -> dict:
        path = self._repo_path(source)
        if not path:
            return {
                "ok": bool(source.remote_url),
                "local": False,
                "remote_url": source.remote_url,
                "message": "no local path; remote registered only",
            }
        r = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
        ok = r.returncode == 0 and r.stdout.strip() == "true"
        fsck = _run_git(["fsck", "--no-dangling", "--no-progress"], cwd=path, timeout=60)
        return {
            "ok": ok and fsck.returncode == 0,
            "local": True,
            "path": path,
            "fsck_ok": fsck.returncode == 0,
            "message": fsck.stderr.strip()[:500] if fsck.returncode != 0 else "ok",
        }
