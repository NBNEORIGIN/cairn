from __future__ import annotations

from pathlib import Path

from .loader import SkillDefinition, SkillLoader


class SkillManager:
    MAX_ACTIVE_SKILLS = 2
    CONTEXT_BUDGET_TOKENS = 700

    def __init__(self, project_id: str, projects_root: Path | None = None):
        self.project_id = project_id
        if projects_root is None:
            projects_root = Path(__file__).resolve().parents[2] / 'projects'
        self.loader = SkillLoader(project_id=project_id, projects_root=projects_root)

    def all_skills(self) -> list[SkillDefinition]:
        return self.loader.load_all()

    def list_skills(self) -> list[SkillDefinition]:
        return self.all_skills()

    def match(
        self,
        query: str,
        subproject_id: str | None = None,
    ) -> list[SkillDefinition]:
        query_lower = query.lower()
        matched: list[SkillDefinition] = []

        for skill in self.all_skills():
            if subproject_id and skill.subproject_id == subproject_id:
                matched.append(skill)
                continue
            for trigger in skill.triggers:
                if trigger.lower() in query_lower:
                    matched.append(skill)
                    break

        seen: set[str] = set()
        unique: list[SkillDefinition] = []
        for skill in matched:
            if skill.skill_id in seen:
                continue
            seen.add(skill.skill_id)
            unique.append(skill)
            if len(unique) >= self.MAX_ACTIVE_SKILLS:
                break
        return unique

    def resolve(self, skill_ids: list[str] | None) -> list[SkillDefinition]:
        requested = set(skill_ids or [])
        if not requested:
            return []
        skills = []
        for skill in self.all_skills():
            if skill.skill_id in requested:
                skills.append(skill)
        return skills[: self.MAX_ACTIVE_SKILLS]

    def resolve_for_request(
        self,
        query: str,
        subproject_id: str | None = None,
        manual_skill_ids: list[str] | None = None,
    ) -> list[SkillDefinition]:
        # Phase 1 keeps skills explicit and predictable: only manually selected
        # skills are activated for a request. The query/subproject arguments stay
        # in the signature so later classifiers can be added without changing the
        # agent contract.
        return self.resolve(manual_skill_ids)

    def build_context(self, skills: list[SkillDefinition]) -> str:
        if not skills:
            return ''

        per_skill_budget = max(120, int(self.CONTEXT_BUDGET_TOKENS / len(skills)))
        blocks: list[str] = []
        for skill in skills:
            lines = [
                f"## Skill: {skill.display_name}",
                f"Domain: {skill.description}",
            ]
            if skill.prompt_hint:
                lines.append(f"Hint: {skill.prompt_hint}")
            if skill.key_rules:
                lines.append("Key rules:")
                lines.extend(f"- {rule}" for rule in skill.key_rules)
            decisions = self._recent_decisions(skill)
            if decisions:
                lines.append("Recent decisions:")
                lines.extend(f"- {decision}" for decision in decisions)

            block = '\n'.join(lines).strip()
            words = block.split()
            max_words = max(1, int(per_skill_budget / 1.3))
            if len(words) > max_words:
                block = ' '.join(words[:max_words]) + ' …'
            blocks.append(block)

        return '\n\n'.join(blocks)

    def build_context_blocks(self, skills: list[SkillDefinition]) -> list[str]:
        if not skills:
            return []
        block = self.build_context(skills)
        return [part for part in block.split('\n\n') if part.strip()]

    def active_skill_ids(self, skills: list[SkillDefinition]) -> list[str]:
        return [skill.skill_id for skill in skills]

    def derived_subproject_id(self, skills: list[SkillDefinition]) -> str | None:
        for skill in skills:
            if skill.subproject_id:
                return skill.subproject_id
        return None

    def primary_subproject_id(self, skills: list[SkillDefinition]) -> str | None:
        return self.derived_subproject_id(skills)

    def _recent_decisions(self, skill: SkillDefinition, max_bullets: int = 3) -> list[str]:
        if not skill.decisions_path.exists():
            return []
        bullets = []
        for line in skill.decisions_path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if stripped.startswith('- '):
                bullets.append(stripped[2:].strip())
        return bullets[-max_bullets:]
