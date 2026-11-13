"""Dispatch parsed command names to the corresponding workflow."""

from . import ai, query, records, source, workspace


HANDLERS = {
    'ai-test': ai.test,
    'ai-status': ai.status,
    'ai-config': ai.config,
    'ai-proposals': ai.proposals,
    'doctor': workspace.doctor,
    'snapshot': workspace.snapshots,
    'inputs': workspace.inputs,
    'human-build': workspace.human_build,
    'asset-add': workspace.asset_add,
    'research-import': records.workspace_records,
    'review-list': records.workspace_records,
    'software-import-seed': records.workspace_records,
    'software-coverage': records.workspace_records,
    'software-refresh': records.workspace_records,
    'search': query.graph_query,
    'show': query.graph_query,
    'deps': query.graph_query,
    'impact': query.graph_query,
    'context': query.graph_query,
    'mcp-config': query.mcp_config,
    'serve-mcp': query.mcp_serve,
    'query-tool': query.query_tool,
    'split': source.split,
    'check-css': records.check_css,
    'check-experiment': records.check_experiment,
    'codes': query.research_query,
    'query-performance': query.research_query,
    'query-software': query.research_query,
}
