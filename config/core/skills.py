from dataclasses import dataclass
from pathlib import Path

from .frontmatter import parse_frontmatter


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    content: str | None = None
    reference: dict[str, str] | None = None
    script: dict[str, str] | None = None


class SkillManager:
    """Discover and load skills from a directory."""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self.registry: dict[str, Skill] = {}
        self._scan_skills()

    def list_skills(self) -> list[dict[str, str]]:
        """Return skill metadata for the language model."""
        return [
            {"name": skill.name, "description": skill.description}
            for skill in self.registry.values()
        ]

    def _scan_skills(self) -> None:
        """Scan first-level directories for SKILL.md manifests."""
        if not self.skills_dir.is_dir():
            return

        for directory in self.skills_dir.iterdir():
            if not directory.is_dir():
                continue

            manifest = directory / "SKILL.md"
            ref_dir = directory / "reference"
            script_dir = directory / "script"

            if not manifest.is_file():
                continue

            text = manifest.read_text()

            reference: dict[str, str] = {}
            if ref_dir.is_dir():
                for ref in ref_dir.glob("*.md"):
                    if not ref.is_file():
                        continue
                    ref_content = ref.read_text()
                    if ref_content:
                        reference[ref.name] = ref_content

            script: dict[str, str] = {}
            if script_dir.is_dir():
                for scp in script_dir.glob("*.py"):
                    if not scp.is_file():
                        continue
                    script_content = scp.read_text()
                    if script_content:
                        script[scp.name] = script_content

            metadata, content = parse_frontmatter(text)
            normalized_content = content.strip()
            if not normalized_content:
                continue

            name = metadata.get("name", directory.name)
            description = metadata.get(
                "description",
                normalized_content.splitlines()[0].lstrip("#").strip(),
            )
            if not isinstance(name, str) or not isinstance(description, str):
                continue

            name = name.strip()
            description = description.strip()
            if not name or not description:
                continue

            self.registry[name] = Skill(
                name=name,
                description=description,
                path=manifest,
                content=content,
                reference=reference,
                script=script,
            )

    def load_skill(self, name: str) -> str:
        """Load a skill's full instruction body by name."""
        skill = self.registry.get(name)
        if skill is None:
            return f"skill {name} not found in registry."
        if not skill.reference and not skill.script:
            return skill.content or ""
        return (
            f"Skill content: {skill.content}, reference: {skill.reference}, "
            f"script: {skill.script}."
        )
