import os
import tempfile
import unittest
from pathlib import Path

from qecgraph.llm.config import AIConfigError, load_ai_config, render_config_template


class AIConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def write(self, text):
        (self.root / 'qecgraph.toml').write_text(text, encoding='utf-8')

    def test_template_contains_mainstream_providers_and_requires_a_model(self):
        self.write(render_config_template('workspace:test'))
        config = load_ai_config(self.root, environ={})
        self.assertEqual(config.provider, 'openrouter')
        self.assertEqual(sorted(config.providers), ['anthropic', 'claude_code', 'openai', 'openrouter'])
        with self.assertRaisesRegex(AIConfigError, r'\.model is empty'):
            config.require_ready(environ={})

    def test_selected_provider_uses_env_or_inline_key(self):
        self.write(render_config_template('workspace:test').replace('model = ""', 'model = "test-model"'))
        config = load_ai_config(self.root, environ={'OPENROUTER_API_KEY': 'env-secret'})
        self.assertEqual(config.require_ready({'OPENROUTER_API_KEY': 'env-secret'}).name, 'openrouter')
        self.assertEqual(config.selected.resolved_key({'OPENROUTER_API_KEY': 'env-secret'}), 'env-secret')
        with self.assertRaisesRegex(AIConfigError, 'missing API key'):
            config.require_ready(environ={})

    def test_cli_provider_needs_no_api_key(self):
        self.write(render_config_template('workspace:test')
                   .replace('provider = "openrouter"', 'provider = "claude_code"')
                   .replace('model = ""', 'model = "cli-model"'))
        config = load_ai_config(self.root)
        self.assertEqual(config.require_ready().kind, 'cli')

    def test_unknown_provider_and_bad_provider_kind_are_rejected(self):
        self.write(render_config_template('workspace:test'))
        text = (self.root / 'qecgraph.toml').read_text(encoding='utf-8')
        self.write(text.replace('provider = "openrouter"', 'provider = "missing"').replace('model = ""', 'model = "test-model"'))
        with self.assertRaisesRegex(AIConfigError, 'must name one of'):
            load_ai_config(self.root).require_ready()
        self.write(text.replace('kind = "openai_compatible"', 'kind = "nope"'))
        with self.assertRaisesRegex(AIConfigError, r'\.kind must be one of'):
            load_ai_config(self.root)

    def test_source_upload_switch_is_boolean(self):
        self.write(render_config_template('workspace:test')
                   .replace('allow_source_upload = true', 'allow_source_upload = "yes"'))
        with self.assertRaisesRegex(AIConfigError, 'allow_source_upload'):
            load_ai_config(self.root)
