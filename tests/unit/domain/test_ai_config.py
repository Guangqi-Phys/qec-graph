import tempfile
import unittest
from pathlib import Path

from qecgraph.llm.config import AIConfigError, DEFAULT_MODEL, load_ai_config, render_config_template


class AIConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def write(self, text):
        (self.root / 'qecgraph.toml').write_text(text, encoding='utf-8')

    def test_template_defaults_to_openrouter_and_requires_user_credentials(self):
        self.write(render_config_template('workspace:test'))
        config = load_ai_config(self.root, environ={})
        self.assertEqual(config.provider, 'openrouter')
        self.assertEqual(config.model, 'deepseek/deepseek-v4.1-flash-1017')
        self.assertTrue(config.enabled)
        self.assertTrue(config.extract_proposals)
        self.assertEqual(config.selected.base_url, 'https://openrouter.ai/api/v1')
        self.assertEqual(config.selected.api_key_env, 'OPENROUTER_API_KEY')
        self.assertTrue(all(provider.api_key is None for provider in config.providers.values()))
        self.assertEqual(config.max_parallel_packages, 1)
        self.assertEqual(sorted(config.providers), ['anthropic', 'claude_code', 'openai', 'openrouter'])
        with self.assertRaisesRegex(AIConfigError, 'missing API key'):
            config.require_ready(environ={})

    def test_omitted_selection_and_proposal_flag_use_the_same_defaults(self):
        self.write('[ai]\n[ai.providers.openrouter]\n')
        config = load_ai_config(self.root)
        self.assertEqual(config.provider, 'openrouter')
        self.assertEqual(config.model, 'deepseek/deepseek-v4.1-flash-1017')
        self.assertTrue(config.extract_proposals)
        self.assertIsNone(config.selected.resolved_key({}))

    def test_explicit_old_configuration_is_preserved(self):
        self.write('[ai]\nprovider = "openai"\nmodel = ""\n'
                   'extract_proposals = false\n[ai.providers.openai]\n')
        config = load_ai_config(self.root)
        self.assertEqual(config.provider, 'openai')
        self.assertEqual(config.model, '')
        self.assertFalse(config.extract_proposals)
        with self.assertRaisesRegex(AIConfigError, r'\.model is empty'):
            config.require_ready(environ={})

    def test_selected_provider_uses_env_or_inline_key(self):
        self.write(render_config_template('workspace:test').replace(f'model = "{DEFAULT_MODEL}"', 'model = "test-model"'))
        config = load_ai_config(self.root, environ={'OPENROUTER_API_KEY': 'env-secret'})
        self.assertEqual(config.model, 'test-model')
        self.assertEqual(config.require_ready({'OPENROUTER_API_KEY': 'env-secret'}).name, 'openrouter')
        self.assertEqual(config.selected.resolved_key({'OPENROUTER_API_KEY': 'env-secret'}), 'env-secret')
        with self.assertRaisesRegex(AIConfigError, 'missing API key'):
            config.require_ready(environ={})

    def test_cli_provider_needs_no_api_key(self):
        self.write(render_config_template('workspace:test')
                   .replace('provider = "openrouter"', 'provider = "claude_code"')
                   .replace(f'model = "{DEFAULT_MODEL}"', 'model = "cli-model"'))
        config = load_ai_config(self.root)
        self.assertEqual(config.require_ready().kind, 'cli')

    def test_unknown_provider_and_bad_provider_kind_are_rejected(self):
        self.write(render_config_template('workspace:test'))
        text = (self.root / 'qecgraph.toml').read_text(encoding='utf-8')
        self.write(text.replace('provider = "openrouter"', 'provider = "missing"'))
        with self.assertRaisesRegex(AIConfigError, 'must name one of'):
            load_ai_config(self.root).require_ready()
        self.write(text.replace('kind = "openai_compatible"', 'kind = "nope"'))
        with self.assertRaisesRegex(AIConfigError, r'\.kind must be one of'):
            load_ai_config(self.root)

    def test_parallel_package_limit_is_validated(self):
        self.write(render_config_template('workspace:test').replace('max_parallel_packages = 1', 'max_parallel_packages = 4'))
        self.assertEqual(load_ai_config(self.root).max_parallel_packages, 4)
        self.write(render_config_template('workspace:test').replace('max_parallel_packages = 1', 'max_parallel_packages = 0'))
        with self.assertRaisesRegex(AIConfigError, 'max_parallel_packages'):
            load_ai_config(self.root)

    def test_source_upload_switch_is_boolean(self):
        self.write(render_config_template('workspace:test')
                   .replace('allow_source_upload = true', 'allow_source_upload = "yes"'))
        with self.assertRaisesRegex(AIConfigError, 'allow_source_upload'):
            load_ai_config(self.root)
