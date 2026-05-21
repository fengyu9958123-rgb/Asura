"""State definitions for the isolated LangGraph image pipeline."""

from typing import Any, Dict, List, Optional, TypedDict


class GraphPipelineState(TypedDict, total=False):
    module_id: str
    task_id: str
    module_name: str
    output_dir: str
    phase: str
    current_node: str
    status: str
    error: str
    needs_confirmation: bool

    image_analysis_path: str
    prd_draft_path: str
    prd_review_path: str
    confirmation_items_path: str
    confirmation_answers_path: str
    final_prd_path: str
    test_cases_path: str
    test_results_path: str
    testcase_artifact_dir: str
    testcase_artifact_index: str
    result_index_path: str

    # Small in-memory values used only inside one process run.
    image_analyses: Dict[str, Any]
    prd_content: str
    confirmation_items: List[Dict[str, Any]]
    confirmation_answers: Dict[str, str]
    final_prd: str
    test_results: Dict[str, Any]


def public_state(state: GraphPipelineState) -> Dict[str, Any]:
    """Return a small persisted state without large transient values."""
    omitted = {
        "image_analyses",
        "prd_content",
        "confirmation_items",
        "confirmation_answers",
        "final_prd",
        "test_results",
    }
    return {key: value for key, value in dict(state).items() if key not in omitted}
