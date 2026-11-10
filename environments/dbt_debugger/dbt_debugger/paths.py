"""Project-relative path resolution and ``artifact_manifest`` glob matching."""

from __future__ import annotations

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

DEBUG_CONTEXT_GLOB = "debug_context/**"
_EXTRA_READ_GLOBS = (DEBUG_CONTEXT_GLOB, "target/**", "logs/**")


def normalize_rel_path(path: str) -> str:
    """Return a POSIX relative path with no leading ``./`` or ``..`` segments."""
    parts: list[str] = []
    for seg in path.strip().replace("\\", "/").lstrip("/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError("Path must not contain '..'")
        parts.append(seg)
    return "/".join(parts)


def resolve_under_root(rel: str, project_root: Path) -> Path:
    """Resolve a project-relative path while preventing root escape."""
    root = project_root.resolve()
    rel_n = normalize_rel_path(rel)
    if not rel_n:
        return root
    candidate = (root / rel_n).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes project root") from exc
    return candidate


@lru_cache(maxsize=512)
def _path_segments(path: str) -> tuple[str, ...]:
    return tuple(seg for seg in normalize_rel_path(path).split("/") if seg)


@lru_cache(maxsize=512)
def _glob_segments(pattern: str) -> tuple[str, ...]:
    cleaned = pattern.replace("\\", "/").strip().lstrip("/")
    return tuple(seg for seg in cleaned.split("/") if seg not in ("", "."))


def _glob_matches_segments(
    path_segments: tuple[str, ...], pattern_segments: tuple[str, ...]
) -> bool:
    """Match path segments against glob segments, where ``**`` spans zero or more."""
    memo: dict[tuple[int, int], bool] = {}

    def _match(path_idx: int, pat_idx: int) -> bool:
        key = (path_idx, pat_idx)
        if key not in memo:
            if pat_idx == len(pattern_segments):
                result = path_idx == len(path_segments)
            elif pattern_segments[pat_idx] == "**":
                result = _match(path_idx, pat_idx + 1) or (
                    path_idx < len(path_segments) and _match(path_idx + 1, pat_idx)
                )
            else:
                result = path_idx < len(path_segments) and (
                    fnmatchcase(path_segments[path_idx], pattern_segments[pat_idx])
                    and _match(path_idx + 1, pat_idx + 1)
                )
            memo[key] = result
        return memo[key]

    return _match(0, 0)


def path_matches_globs(rel_posix: str, globs: list[str]) -> bool:
    """Return ``True`` if *rel_posix* matches any manifest glob with real ``**`` semantics."""
    path_segments = _path_segments(rel_posix)
    return any(
        _glob_matches_segments(path_segments, _glob_segments(pattern))
        for pattern in (raw.replace("\\", "/").strip() for raw in globs)
        if pattern
    )


def globs_for_list_and_search(manifest_globs: list[str]) -> list[str]:
    """Append ``debug_context/**`` when missing so list/search can see debug_context."""
    out = list(manifest_globs)
    if not any(
        g.replace("\\", "/").strip().endswith(DEBUG_CONTEXT_GLOB) for g in out
    ):
        out.append(DEBUG_CONTEXT_GLOB)
    return out


def effective_read_globs(manifest_globs: list[str]) -> list[str]:
    """Extend manifest read globs with rollout debug artifacts."""
    return [*manifest_globs, *_EXTRA_READ_GLOBS]
