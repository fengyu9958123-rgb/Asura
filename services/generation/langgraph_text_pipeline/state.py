"""State definitions for the isolated LangGraph text PRD pipeline."""

from typing import Any, Dict, List, TypedDict


class TextGraphPipelineState(TypedDict, total=False):
    prd_id: str
    task_id: str
    task_name: str
    business: str
    output_dir: str
    phase: str
    current_node: str
    status: str
    error: str
    needs_confirmation: bool

    original_prd_path: str
    cleaned_prd_path: str
    review_result_path: str
    confirmation_items_path: str
    confirmation_answers_path: str
    final_prd_path: str
    test_results_path: str
    testcase_artifact_dir: str
    testcase_artifact_index: str
    result_index_path: str

    original_prd: str
    cleaned_prd: str
    review_result: Dict[str, Any]
    confirmation_items: List[Dict[str, Any]]
    confirmation_answers: Dict[str, str]
    final_prd: str
    test_results: Dict[str, Any]


def public_state(state: TextGraphPipelineState) -> Dict[str, Any]:
    omitted = {
        "original_prd",
        "cleaned_prd",
        "review_result",
        "confirmation_items",
        "confirmation_answers",
        "final_prd",
        "test_results",
    }
    return {key: value for key, value in dict(state).items() if key not in omitted}
