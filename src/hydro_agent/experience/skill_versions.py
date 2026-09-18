from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select

from hydro_agent.experience.compiler import CompiledExperienceSkill
from hydro_agent.persistence.models import ExperienceSkillVersion
from hydro_agent.skills.loader import load_skills

_SKILL_ID = "calibration-experience"


class ExperienceSkillVersionStore:
    def __init__(self, root: Path, *, repository):
        self.root = Path(root)
        self.repository = repository

    @property
    def current_root(self) -> Path:
        return self.root / "current"

    @property
    def versions_root(self) -> Path:
        return self.root / "versions"

    @property
    def current_package(self) -> Path:
        return self.current_root / _SKILL_ID

    def create_candidate(
        self,
        compiled: CompiledExperienceSkill,
    ) -> ExperienceSkillVersion:
        version_dir = self._version_dir(compiled.version)
        if version_dir.exists():
            raise ValueError(f"experience skill version already exists: {compiled.version}")

        self.versions_root.mkdir(parents=True, exist_ok=True)
        temp_version = self.versions_root / f".v{compiled.version:03d}.tmp"
        if temp_version.exists():
            shutil.rmtree(temp_version)
        package = temp_version / _SKILL_ID
        self._write_package(package, compiled.files)
        self._validate_package_root(temp_version)

        temp_version.replace(version_dir)
        current = self.repository.get_current_experience_skill_version()
        try:
            return self.repository.create_experience_skill_version(
                version=compiled.version,
                parent_version=current.version if current is not None else None,
                status="candidate",
                skill_hash=compiled.sha256,
                manifest={
                    "skill_id": _SKILL_ID,
                    "source": "agent",
                    "files": sorted(compiled.files),
                    "sha256": compiled.sha256,
                },
            )
        except Exception:
            shutil.rmtree(version_dir, ignore_errors=True)
            raise

    def promote(self, version: int) -> ExperienceSkillVersion:
        version_package = self.materialize(version)
        self.current_root.mkdir(parents=True, exist_ok=True)

        temp_package = self.current_root / f".{_SKILL_ID}.tmp"
        backup_package = self.current_root / f".{_SKILL_ID}.old"
        for path in (temp_package, backup_package):
            if path.exists():
                shutil.rmtree(path)
        shutil.copytree(version_package, temp_package)
        self._validate_package_root(self.current_root, directory_name=temp_package.name)

        swapped = False
        try:
            with self.repository.database.session() as session:
                candidate = session.get(ExperienceSkillVersion, version)
                if candidate is None:
                    raise KeyError(version)
                if candidate.status != "candidate":
                    raise ValueError(
                        f"experience skill version {version} is not candidate"
                    )
                previous = session.scalar(
                    select(ExperienceSkillVersion)
                    .where(
                        ExperienceSkillVersion.status == "promoted",
                        ExperienceSkillVersion.version != version,
                    )
                    .order_by(ExperienceSkillVersion.version.desc())
                    .limit(1)
                )

                if self.current_package.exists():
                    self.current_package.replace(backup_package)
                temp_package.replace(self.current_package)
                swapped = True

                candidate.status = "promoted"
                if previous is not None:
                    previous.status = "superseded"
                session.flush()
        except Exception:
            if swapped:
                shutil.rmtree(self.current_package, ignore_errors=True)
                if backup_package.exists():
                    backup_package.replace(self.current_package)
            shutil.rmtree(temp_package, ignore_errors=True)
            raise
        else:
            shutil.rmtree(backup_package, ignore_errors=True)

        return self.repository.get_experience_skill_version(version)

    def reject(self, version: int, reason: str) -> ExperienceSkillVersion:
        if not reason.strip():
            raise ValueError("rejection reason required")
        return self.repository.set_experience_skill_version_status(
            version,
            "rejected",
            regression={
                "passed": False,
                "reason": reason.strip(),
            },
        )

    def materialize(self, version: int) -> Path:
        package = self._version_dir(version) / _SKILL_ID
        if not (package / "SKILL.md").is_file():
            raise KeyError(version)
        self._validate_package_root(package.parent)
        return package

    def _version_dir(self, version: int) -> Path:
        if version < 1:
            raise ValueError("version must be >= 1")
        return self.versions_root / f"v{version:03d}"

    @staticmethod
    def _write_package(package: Path, files: dict[str, str]) -> None:
        for relative, content in sorted(files.items()):
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    @staticmethod
    def _validate_package_root(root: Path, *, directory_name: str = _SKILL_ID) -> None:
        if directory_name == _SKILL_ID:
            loaded = load_skills(root)
            if _SKILL_ID not in loaded:
                raise ValueError("compiled Experience Skill package is invalid")
            return

        package = root / directory_name
        canonical = root / _SKILL_ID
        package.replace(canonical)
        try:
            loaded = load_skills(root)
            if _SKILL_ID not in loaded:
                raise ValueError("compiled Experience Skill package is invalid")
        finally:
            canonical.replace(package)
