import json
import tempfile
import unittest
from pathlib import Path

from qecgraph.llm.skills import SkillError, load_skills


class SkillTests(unittest.TestCase):
    def test_default_skill_packs_load_with_valid_schemas(self):
        skills = load_skills()
        self.assertEqual(sorted(skills), ['extract_assumptions', 'extract_data',
                                          'extract_theorems', 'normalize_package'])
        for name, skill in skills.items():
            self.assertEqual(skill.name, name)
            self.assertGreaterEqual(skill.version, 1)
            self.assertIn('JSON', skill.prompt)
            self.assertTrue(skill.schema.get('properties'))

    def test_workspace_skill_can_override_a_default_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'extract_theorems'
            root.mkdir()
            (root / 'SKILL.md').write_text(
                '---\nname: extract_theorems\ndescription: override\nversion: 2\n---\nbody\n',
                encoding='utf-8')
            (root / 'prompt.md').write_text('Return only JSON.', encoding='utf-8')
            schema = {'type': 'object', 'required': ['items'],
                      'properties': {'items': {'type': 'array'}}}
            (root / 'output.schema.json').write_text(json.dumps(schema), encoding='utf-8')
            skills = load_skills(Path(directory))
            self.assertEqual(skills['extract_theorems'].version, 2)
            self.assertEqual(skills['extract_theorems'].description, 'override')

    def test_missing_or_mismatched_pack_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'missing'
            root.mkdir()
            (root / 'SKILL.md').write_text('---\nname: missing\ndescription: x\nversion: 1\n---\nbody\n',
                                           encoding='utf-8')
            with self.assertRaisesRegex(SkillError, 'missing prompt.md'):
                load_skills(Path(directory))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'minimal'
            root.mkdir()
            (root / 'SKILL.md').write_text('---\nname: other\nversion: 1\n---\nbody\n',
                                           encoding='utf-8')
            (root / 'prompt.md').write_text('x', encoding='utf-8')
            (root / 'output.schema.json').write_text('{"type": "object"}', encoding='utf-8')
            with self.assertRaisesRegex(SkillError, 'skill name must match|description'):
                load_skills(Path(directory))
