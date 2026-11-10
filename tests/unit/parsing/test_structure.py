import json
import unittest

from qecgraph.llm.client import LLMClient
from qecgraph.llm.providers.base import Completion
from qecgraph.llm.structure import recover_structure
from qecgraph.source.structure import StructureError, StructureIneligible, StructureNeedsReview, body_evidence
from tests.unit.domain.test_ai_client import FakeProvider, config


TEX = r"""\documentclass{article}
% PREAMBLE_ONLY
\begin{document}
\section{正文}
\textbf{λ} cites \cite{example}.
\begin{thebibliography}{1}
\providecommand\href[0]{\@href}
\bibitem{example} Example \unsupported{part
\end{thebibliography}
Later source.
\end{document}
""".replace('\n', '\r\n').encode()


def row(kind, start, end=None):
    return {'kind': kind, 'first_line': start, 'last_line': start if end is None else end}


def plan():
    return {'status': 'ready', 'blocks': [
        row('section', 4), row('paragraph', 5), row('bibliography', 6, 9), row('unknown', 10),
    ]}


class StructurePlanTests(unittest.TestCase):
    def complete(self, result, raw=TEX):
        provider = FakeProvider(Completion(json.dumps(result), 'offline'))
        client = LLMClient(config(), provider=provider)
        return recover_structure(body_evidence('main.tex', raw), client)

    def test_materializes_exact_utf8_crlf_slices_and_literal_citation(self):
        parsed = self.complete(plan())
        blocks = parsed['blocks']
        self.assertEqual([b['kind'] for b in blocks], ['section', 'paragraph', 'paragraph', 'paragraph'])
        self.assertEqual(blocks[0]['title_tex'], '正文')
        self.assertEqual(blocks[1]['parent_key'], blocks[0]['key'])
        self.assertEqual(blocks[2]['source_role'], 'bibliography')
        self.assertEqual(blocks[3]['structure_classification'], 'unknown')
        text = TEX.decode()
        for block in blocks:
            span = block['source']
            self.assertEqual(text[span['char_start']:span['char_end']], block['latex'])
        citation, = blocks[1]['references']
        span = citation['source']
        self.assertEqual(text[span['char_start']:span['char_end']], r'\cite{example}')
        self.assertEqual(citation['targets'], ['example'])
        self.assertNotIn('PREAMBLE_ONLY', json.dumps(body_evidence('main.tex', TEX).request()))

    def test_rejects_gaps_overlap_false_bibliography_and_invented_fields(self):
        cases = [
            [row('section', 4), row('bibliography', 6, 9), row('unknown', 10)],
            [row('section', 4), row('paragraph', 4, 5), row('bibliography', 6, 9), row('unknown', 10)],
            [row('section', 4), row('bibliography', 5, 9), row('unknown', 10)],
            [row('paragraph', 4), row('paragraph', 5), row('bibliography', 6, 9), row('unknown', 10)],
        ]
        for blocks in cases:
            with self.subTest(blocks=blocks), self.assertRaises(StructureError):
                self.complete({'status': 'ready', 'blocks': blocks})
        from qecgraph.llm.client import ResponseSchemaError
        forged = plan()
        forged['blocks'][1]['latex'] = 'invented theorem'
        with self.assertRaises(ResponseSchemaError):
            self.complete(forged)

    def test_declined_and_ineligible_sources_remain_unclassified(self):
        with self.assertRaises(StructureNeedsReview):
            self.complete({'status': 'needs_review', 'blocks': []})
        for raw in (TEX.replace(b'Later source.', rb'\input{missing}'),
                    TEX.replace(b'Later source.', rb'\begin{document}'),
                    TEX.replace(b'Later source.', rb'\def\unsafe{hidden}')):
            with self.subTest(raw=raw), self.assertRaises(StructureIneligible):
                body_evidence('main.tex', raw)
