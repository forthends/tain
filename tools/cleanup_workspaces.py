"""
One-shot cleanup: migrate existing agent workspaces to the semantic layout.

Run once: python tools/cleanup_workspaces.py
"""
import shutil
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / "agent_workspace"

# ── Workspace-specific legacy merge plans ──────────────────────────
# (source_dir, dest_dir) — merge source contents into dest, then remove source

LEGACY_DIR_MERGES: list[tuple[str, str]] = [
    ("poems", "poetry"),
    ("poetic_moments", "poetry/moments"),
    ("poetry_garden", "poetry"),
    ("poetry_journal", "journal"),
    ("knowledge_garden", "knowledge"),
    ("rag_index", "knowledge"),
    ("commitment_letters", "commitments"),
]

# ── Root-level files to move into canonical directories ────────────

ROOT_FILE_MOVES: dict[str, str] = {
    "poetry-self-portrait.md": "journal/",
    "poetry_moments.json": "poetry/moments/",
    "evolution_milestones.jsonl": "reports/",
    "test_liminal_tool.py": "tests/",
    "test_forged_tool_v2.py": "tests/",
}

# ── Canonical directories to ensure exist ──────────────────────────

REQUIRED_DIRS: list[str] = [
    "poetry/",
    "poetry/moments/",
    "knowledge/",
    "knowledge/concepts/",
    "knowledge/research/",
    "journal/",
    "commitments/",
    "goals/",
    "reports/",
    "forged_tools/",
    "tests/",
    "files/",
    "logs/",
    "logs/conversations/",
    "state/",
]


def clean_workspace(agent_dir: Path, name: str) -> None:
    """Clean up a single agent workspace."""
    print(f"\n{'='*60}")
    print(f"Cleaning: {name} ({agent_dir})")
    print(f"{'='*60}")

    # 1. Ensure canonical directories exist
    for d in REQUIRED_DIRS:
        (agent_dir / d).mkdir(parents=True, exist_ok=True)

    # 2. Merge legacy directories
    for src_rel, dst_rel in LEGACY_DIR_MERGES:
        src = agent_dir / src_rel
        dst = agent_dir / dst_rel
        if not src.exists() or not src.is_dir():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        moved = 0
        for item in src.iterdir():
            target = dst / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
                moved += 1
            elif item.is_file():
                # File exists at dest — compare contents, keep the bigger file
                src_size = item.stat().st_size
                dst_size = target.stat().st_size
                if src_size > dst_size:
                    shutil.move(str(item), str(target))
                    print(f"  [overwrite] {item.name} ({src_size} > {dst_size} bytes)")
                else:
                    print(f"  [skip] {item.name} (dest is larger or equal)")
        # Remove legacy dir if empty
        if moved and not any(src.iterdir()):
            src.rmdir()
            print(f"  [merge] {src_rel}/ → {dst_rel}/ ({moved} files)")
        elif moved:
            print(f"  [merge] {src_rel}/ → {dst_rel}/ ({moved} files, dir kept: not empty)")

    # 3. Move root-level files to canonical locations
    for filename, dest_rel in ROOT_FILE_MOVES.items():
        src = agent_dir / filename
        if not src.exists() or not src.is_file():
            continue
        dst = agent_dir / dest_rel / filename
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            print(f"  [move] {filename} → {dest_rel}{filename}")

    # 4. Remove empty legacy directories (those in LEGACY_DIR_MERGES that still exist but are empty)
    # Also remove any empty standalone dirs
    for src_rel, _ in LEGACY_DIR_MERGES:
        src = agent_dir / src_rel
        if src.exists() and src.is_dir():
            try:
                src.rmdir()
                print(f"  [rmdir] {src_rel}/ (empty)")
            except OSError:
                # Not empty
                pass

    # 5. Ensure version.json is in state/ (if it exists at root and not in state)
    root_version = agent_dir / "version.json"
    state_version = agent_dir / "state" / "version.json"
    if root_version.exists() and not state_version.exists():
        state_version.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(root_version), str(state_version))
        print(f"  [copy] version.json → state/version.json (original kept for compatibility)")

    print(f"Done: {name}")


def main():
    if not WORKSPACE_ROOT.exists():
        print(f"Workspace root not found: {WORKSPACE_ROOT}")
        return

    for entry in sorted(WORKSPACE_ROOT.iterdir()):
        if entry.is_dir() and not entry.name.startswith(("_", ".")):
            clean_workspace(entry, entry.name)

    print(f"\n{'='*60}")
    print("Cleanup complete.")


if __name__ == "__main__":
    main()
