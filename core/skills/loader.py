from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


logger = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    skill_id: str
    project_id: str
    display_name: str
    description: str
    triggers: list[str]
    subproject_id: Optional[str]
    key_rules: list[str]
    prompt_hint: str
    decisions_path: Path


class SkillLoader:
    def __init__(self, project_id: str, projects_root: Path):
        self.project_id = project_id
        self.projects_root = projects_root
        self.skills_root = projects_root / project_id / 'skills'
        self._skills: list[SkillDefinition] | None = None

    def load_all(self) -> list[SkillDefinition]:
        if self._skills is not None:
            return self._skills

        skills: list[SkillDefinition] = []
        if not self.skills_root.exists():
            self._skills = []
            return self._skills

        for path in sorted(self.skills_root.glob('*/skill.yaml')):
            try:
                skills.append(self._load_one(path))
            except Exception as exc:
                logger.warning('[skills] failed to load %s: %s', path, exc)

        self._skills = skills
        return skills

    def _load_one(self, path: Path) -> SkillDefinition:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        required = ['skill_id', 'project_id', 'display_name', 'description']
        missing = [field for field in required if not data.get(field)]
        if missing:
            raise ValueError(f'missing required fields: {", ".join(missing)}')
        if data['project_id'] != self.project_id:
            raise ValueError(
                f"skill project_id {data['project_id']} does not match loader project {self.project_id}"
            )

        return SkillDefinition(
            skill_id=str(data['skill_id']),
            project_id=str(data['project_id']),
            display_name=str(data['display_name']),
            description=str(data['description']),
            triggers=[str(t).strip() for t in data.get('triggers', []) if str(t).strip()],
            subproject_id=(str(data['subproject_id']).strip() if data.get('subproject_id') else None),
            key_rules=[str(rule).strip() for rule in data.get('key_rules', []) if str(rule).strip()],
            prompt_hint=str(data.get('prompt_hint', '')).strip(),
            decisions_path=path.parent / 'decisions.md',
        )
