"""Graph construction for the isolated LangGraph text PRD pipeline."""

from __future__ import annotations

from typing import Any

from .nodes import TextGraphPipelineNodes
from .state import TextGraphPipelineState


def build_graph(nodes: TextGraphPipelineNodes, *, resume: bool = False) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("Text LangGraph pipeline requires installing langgraph and langchain-core") from exc

    graph = StateGraph(TextGraphPipelineState)
    graph.add_node("load_prd", nodes.load_prd())
    graph.add_node("clean_prd", nodes.clean_prd())
    graph.add_node("prd_logic_review", nodes.prd_logic_review())
    graph.add_node("waiting_confirmation", nodes.wait_for_confirmation())
    graph.add_node("final_prd_integrate", nodes.final_prd_integrate())
    graph.add_node("testcase_pipeline", nodes.testcase_pipeline())
    graph.add_node("save_result", nodes.save_result())

    graph.add_edge(START, "load_prd")
    if resume:
        graph.add_edge("load_prd", "final_prd_integrate")
    else:
        graph.add_edge("load_prd", "clean_prd")
        graph.add_edge("clean_prd", "prd_logic_review")
        graph.add_conditional_edges(
            "prd_logic_review",
            nodes.route_after_review,
            {
                "waiting": "waiting_confirmation",
                "continue": "final_prd_integrate",
            },
        )
        graph.add_edge("waiting_confirmation", END)

    graph.add_edge("final_prd_integrate", "testcase_pipeline")
    graph.add_edge("testcase_pipeline", "save_result")
    graph.add_edge("save_result", END)
    return graph.compile()
