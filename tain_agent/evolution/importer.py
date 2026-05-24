"""
Import Pipeline — return-to-factory upgrade flow.

Unpacks a previously exported agent and restores its identity,
knowledge, tools, and memory into the factory for continued evolution.

Design: Phase 3 §6.1.
"""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class ImportResult:
    """Result of a successful import."""
    name: str
    version: str
    source_archive: str
    workspace_dir: str
    restored: dict  # what was restored
    warnings: list[str] = field(default_factory=list)


class ImportPipeline:
    """Import a standalone agent back into the factory for further evolution.

    Usage:
        importer = ImportPipeline()
        result = importer.import_agent("dist/explorer-v0.23.0.tar.gz")
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        self.project_root = _project_root()
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir)
        else:
            self.workspace_dir = self.project_root / "agent_workspace"

    def import_agent(self, archive_path: str) -> ImportResult:
        """Unpack an exported agent and restore it into the workspace.

        Args:
            archive_path: Path to the .tar.gz file.

        Returns:
            ImportResult with details of what was restored.

        Raises:
            FileNotFoundError: If the archive doesn't exist.
            ValueError: If the archive is malformed.
        """
        archive = Path(archive_path)
        if not archive.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        # Step 1: Extract
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(tmp)

            # Find the agent directory (tar extracts to <name>-v<version>/)
            extracted_dirs = [d for d in tmp.iterdir() if d.is_dir()]
            if not extracted_dirs:
                raise ValueError("Archive contains no directories")

            agent_dir = extracted_dirs[0]
            return self._restore(agent_dir, str(archive))

    def _restore(self, agent_dir: Path, archive_path: str) -> ImportResult:
        """Restore agent artifacts from the extracted directory into the workspace."""
        restored = {}
        warnings = []

        # Read identity
        identity_path = agent_dir / "identity.json"
        if identity_path.exists():
            identity_data = json.loads(identity_path.read_text(encoding="utf-8"))
            version = identity_data.get("version", "0.1.0")
            name = identity_data.get("name", "unknown")
        else:
            name = agent_dir.name.rsplit("-v", 1)[0]
            version = "0.1.0"
            identity_data = {}
            warnings.append("identity.json not found in archive")

        # Ensure workspace directories exist
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        ws_state = self.workspace_dir / "state"
        ws_state.mkdir(parents=True, exist_ok=True)

        # Restore identity → state/personality.json
        if identity_data:
            personality_path = ws_state / "personality.json"
            personality_path.write_text(
                json.dumps(identity_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            restored["identity"] = str(personality_path)

        # Write version.json
        version_path = ws_state / "version.json"
        version_path.write_text(
            json.dumps({"version": version, "imported_at": _now_iso(),
                        "source_archive": archive_path},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        restored["version"] = str(version_path)

        # Restore knowledge/
        knowledge_src = agent_dir / "knowledge"
        if knowledge_src.exists() and any(knowledge_src.iterdir()):
            knowledge_dst = self.workspace_dir / "knowledge_garden"
            if knowledge_dst.exists():
                shutil.rmtree(knowledge_dst)
            shutil.copytree(knowledge_src, knowledge_dst,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            doc_count = len(list(knowledge_dst.rglob("*.md")))
            restored["knowledge"] = {
                "path": str(knowledge_dst),
                "documents": doc_count,
            }
        else:
            warnings.append("No knowledge documents found in archive")

        # Restore tools/ → workspace forged_tools/ (as baseline)
        tools_src = agent_dir / "tools"
        if tools_src.exists() and any(tools_src.iterdir()):
            tools_dst = self.workspace_dir / "forged_tools"
            if tools_dst.exists():
                # Merge: copy new tools, skip existing ones with same name
                for tf in tools_src.glob("*.py"):
                    if not tf.name.startswith("_"):
                        dst = tools_dst / tf.name
                        if not dst.exists():
                            shutil.copy2(tf, dst)
            else:
                tools_dst.mkdir(parents=True)
                for tf in tools_src.glob("*.py"):
                    if not tf.name.startswith("_"):
                        shutil.copy2(tf, tools_dst / tf.name)
            restored["tools"] = {
                "path": str(tools_dst),
                "count": len([f for f in tools_dst.glob("*.py")
                             if not f.name.startswith("_")]),
            }
        else:
            warnings.append("No tools found in archive")

        # Restore memory.json → workspace state/
        memory_src = agent_dir / "memory.json"
        if memory_src.exists():
            memory_dst = ws_state / "memory.json"
            shutil.copy2(memory_src, memory_dst)
            restored["memory"] = str(memory_dst)

        # Restore drives
        if identity_data and "drives" in identity_data:
            drives_path = ws_state / "drives.json"
            drives_path.write_text(
                json.dumps(identity_data["drives"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            restored["drives"] = str(drives_path)

        return ImportResult(
            name=name,
            version=version,
            source_archive=archive_path,
            workspace_dir=str(self.workspace_dir),
            restored=restored,
            warnings=warnings,
        )


def main(action: str = "import_agent", **kwargs) -> dict:
    """CLI entry point for importing an agent."""
    importer = ImportPipeline()
    if action == "import_agent":
        archive_path = kwargs.get("archive_path") or kwargs.get("archive")
        if not archive_path:
            return {"error": "archive_path is required"}
        result = importer.import_agent(archive_path)
        return {
            "imported": True,
            "name": result.name,
            "version": result.version,
            "workspace_dir": result.workspace_dir,
            "restored": result.restored,
            "warnings": result.warnings,
        }
    return {"error": f"Unknown action: {action}"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python importer.py <archive.tar.gz>")
        sys.exit(1)
    result = main(action="import_agent", archive_path=sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
