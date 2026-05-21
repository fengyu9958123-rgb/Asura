"""State definitions for the isolated testcase LangGraph subgraph."""

from typing import Any, Dict, List, TypedDict


class TestcaseGraphState(TypedDict, total=False):
    module_id: str
    task_name: str
    final_prd: str
    testing_notes: str
    output_dir: str
    status: str
    current_node: str
    error: str

    blocked_prd_path: str
    block_plan_path: str
    prd_blocks_path: str
    knowledge_path: str
    context_units_path: str
    unit_results_path: str
    final_cases_path: str
    final_cases_md_path: str
    analysis_path: str
    artifact_index_path: str

    blocked_prd: str
    block_plan: Dict[str, Any]
    prd_blocks: List[Dict[str, Any]]
    knowledge: Dict[str, Any]
    context_units: Dict[str, Any]
    unit_results: List[Dict[str, Any]]
    final_cases: List[Dict[str, Any]]
    quality_review: Dict[str, Any]
    test_results: Dict[str, Any]


def public_state(state: TestcaseGraphState) -> Dict[str, Any]:
    omitted = {
        "final_prd",
        "testing_notes",
        "blocked_prd",
        "block_plan",
        "prd_blocks",
        "knowledge",
        "context_units",
        "unit_results",
        "final_cases",
        "quality_review",
        "test_results",
    }
    return {key: value for key, value in dict(state).items() if key not in omitted}
