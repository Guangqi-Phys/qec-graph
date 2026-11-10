"""Versioned, packageable AI task instructions."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator


class SkillError(ValueError):
    """A skill pack is missing or malformed."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    version: int
    path: Path
    body: str
    prompt: str
    schema: dict

    def validate(self):
        if not self.name or not self.description:
            raise SkillError(f'{self.path}: name and description are required')
        if self.version < 1:
            raise SkillError(f'{self.path}: version must be positive')
        if not isinstance(self.schema, dict) or not self.schema:
            raise SkillError(f'{self.path}: output.schema.json must be an object')
        Draft202012Validator.check_schema(self.schema)
        return self


def _frontmatter(text, path):
    if not text.startswith('---'):
        raise SkillError(f'{path}: SKILL.md must start with YAML frontmatter')
    end = text.find('\n---', 3)
    if end < 0:
        raise SkillError(f'{path}: unterminated frontmatter')
    raw = text[3:end].strip().splitlines()
    values = {}
    for line in raw:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if ':' not in line:
            raise SkillError(f'{path}: invalid frontmatter line {line!r}')
        key, value = line.split(':', 1)
        values[key.strip()] = value.strip().strip('"\'')
    body = text[end + 4:].strip()
    if set(values) - {'name', 'description', 'version'}:
        raise SkillError(f'{path}: unsupported frontmatter keys')
    try:
        version = int(values.get('version', '1'))
    except ValueError as exc:
        raise SkillError(f'{path}: version must be an integer') from exc
    return values.get('name', ''), values.get('description', ''), version, body


def _load(path):
    skill_file = path / 'SKILL.md'
    prompt_file = path / 'prompt.md'
    schema_file = path / 'output.schema.json'
    for required in (skill_file, prompt_file, schema_file):
        if not required.is_file():
            raise SkillError(f'{path}: missing {required.name}')
    name, description, version, body = _frontmatter(skill_file.read_text(encoding='utf-8'), skill_file)
    if name != path.name or not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise SkillError(f'{path}: skill name must match its directory')
    prompt = prompt_file.read_text(encoding='utf-8').strip()
    if not prompt:
        raise SkillError(f'{path}: prompt.md is empty')
    try:
        schema = json.loads(schema_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SkillError(f'{schema_file}: invalid JSON') from exc
    return Skill(name=name, description=description, version=version, path=path,
                 body=body, prompt=prompt, schema=schema).validate()


def load_skills(extra_dir=None):
    root = Path(__file__).with_name('skills')
    skills = {}
    for path in sorted(root.iterdir()):
        if path.is_dir():
            skill = _load(path)
            skills[skill.name] = skill
    if extra_dir is not None:
        extra = Path(extra_dir)
        if extra.is_dir():
            for path in sorted(extra.iterdir()):
                if path.is_dir():
                    skill = _load(path)
                    skills[skill.name] = skill
    if not skills:
        raise SkillError('no AI skills were found')
    return skills


def load_skill(name, extra_dir=None):
    try:
        return load_skills(extra_dir)[name]
    except KeyError as exc:
        raise SkillError(f'unknown AI skill: {name}') from exc
