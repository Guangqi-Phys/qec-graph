import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

from qecgraph.graph import read_json
from qecgraph.records import prepare_record
from qecgraph.review import create_proposal
from qecgraph.validators import packaged_validator


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


class SchemaTests(unittest.TestCase):
    def test_packaged_schemas_and_published_examples(self):
        schemas = files('qecgraph.validators').joinpath('schemas')
        for file in sorted(schemas.iterdir(), key=lambda path: path.name):
            if file.name.endswith('.schema.json'):
                with self.subTest(schema=file.name):
                    validator = packaged_validator(file.name.removesuffix('.schema.json'))
                    Draft202012Validator.check_schema(validator.schema)

        for name in ('annotations.example.json', 'catalog-links.example.json'):
            with self.subTest(example=name):
                packaged_validator('annotations').validate(read_json(EXAMPLES / name))
        for name in ('claim.example.json', 'lean/claim.json'):
            with self.subTest(example=name):
                packaged_validator('record.v3').validate(prepare_record(read_json(EXAMPLES / name)))
        with tempfile.TemporaryDirectory() as directory:
            proposal = create_proposal(directory, actor={'id': 'fixture:docs', 'kind': 'human'},
                                       **read_json(EXAMPLES / 'proposal.example.json'))
            packaged_validator('proposal.v1').validate(proposal)

    def test_research_schema_dispatches_each_supported_kind(self):
        binding = {'id': 'record:fixture', 'revision': 'r1'}
        records = {
            'algorithm': {},
            'catalog_source': {},
            'circuit_protocol': {},
            'classical_seed': {},
            'code_family': {},
            'code_instance': {'coding_domain': 'quantum', 'n_data': 5, 'k_logical': 1},
            'code_mention': {},
            'code_presentation': {'code_ref': None, 'check_weight_metrics': None},
            'construction': {},
            'decoder_configuration': {},
            'distance_claim': {'subject_ref': None, 'metric_definition_ref': None, 'relation': 'lower_bound',
                               'lower_bound': 3, 'upper_bound': None},
            'execution_environment': {},
            'execution_run': {'environment_ref': binding, 'execution_evidence': ['fixture']},
            'hardware_assumptions': {},
            'metric_definition': {},
            'noise_instantiation': {'model_ref': None, 'reported_coordinates': {'p': .01},
                                    'resolved_channel_parameters': None},
            'noise_model': {'idle': None, 'loss': None, 'erasure': None, 'leakage': None},
            'paper_version': {},
            'performance_point': {'experiment_ref': None, 'noise_instantiation_ref': None,
                                  'metric_definition_ref': None, 'value': None},
            'performance_series': {},
            'reported_experiment': {'source_ref': None, 'code_ref': None, 'presentation_ref': None, 'circuit_ref': None,
                                    'noise_model_ref': None, 'decoder_ref': None},
            'software_catalog_observation': {},
            'software_distribution': {'project_ref': binding, 'ecosystem': 'pypi', 'name': 'fixture'},
            'software_project': {},
            'software_release': {'distribution_ref': binding, 'version': '1.0'},
            'software_usage': {'usage_kind': 'mention', 'project_ref': None, 'release_ref': None},
        }
        validator = packaged_validator('research.v1')
        self.assertEqual(set(records), set(validator.schema['properties']['kind']['enum']))
        for kind, data in records.items():
            record = {'schema_version': 'qecgraph.research.v1', 'id': 'record:fixture', 'revision': 'r1', 'kind': kind,
                      'data': data, 'field_evidence': {}, 'is_synthetic': True}
            with self.subTest(kind=kind):
                validator.validate(record)
            for field in data:
                with self.subTest(kind=kind, missing=field):
                    reduced = {name: value for name, value in data.items() if name != field}
                    errors = list(validator.iter_errors({**record, 'data': reduced}))
                    self.assertTrue(any(error.validator == 'required' and error.json_path == '$.data' for error in errors))
