import importlib.util
import shlex
import unittest


from tests.support import ROOT
spec = importlib.util.spec_from_file_location(
    'qec_check_distribution', ROOT / 'tools' / 'check_distribution.py')
check_distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_distribution)


class ContainerAndManifestTests(unittest.TestCase):
    def test_dockerfile_copy_sources_exist_in_the_checkout(self):
        instructions, current = [], ''
        for line in (ROOT / 'Dockerfile').read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if stripped.endswith('\\'):
                current += stripped[:-1] + ' '
                continue
            instructions.append(current + stripped)
            current = ''
        if current:
            instructions.append(current)
        for instruction in instructions:
            parts = shlex.split(instruction)
            if not parts or parts[0].upper() not in {'COPY', 'ADD'}:
                continue
            arguments = [part for part in parts[1:] if not part.startswith('--')]
            sources = arguments[:-1]
            self.assertTrue(len(arguments) >= 2 and sources, instruction)
            for source in sources:
                if '://' in source:
                    continue
                with self.subTest(instruction=instruction, source=source):
                    self.assertTrue((ROOT / source).exists(), f'{source} is copied but missing from the checkout')

    def test_ai_skills_are_declared_package_data(self):
        from qecgraph.llm.skills import load_skills
        text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('"qecgraph.llm"', text)
        self.assertIn('skills/*/*.md', text)
        self.assertIn('skills/*/*.json', text)
        self.assertIn('recover_structure', load_skills())

    def test_source_distribution_manifest_ships_the_chinese_readme(self):
        manifest = (ROOT / 'MANIFEST.in').read_text(encoding='utf-8')
        for name in ('README.zh-CN.md',):
            with self.subTest(name=name):
                self.assertIn(name, manifest)


class DistributionMetadataTests(unittest.TestCase):
    def test_utf8_readme_round_trips_through_email_metadata(self):
        readme = '# QEC Graph\n\nA → B — provenance.\n'
        raw = (
            b'Version: 0.6.0\n'
            b'License-Expression: MIT\n'
            b'License-File: LICENSE\n'
            b'Content-Type: text/markdown; charset=utf-8\n'
            b'Content-Transfer-Encoding: 8bit\n\n' + readme.encode('utf-8')
        )
        check_distribution._check_metadata(raw, '0.6.0', readme)


if __name__ == '__main__':
    unittest.main()
