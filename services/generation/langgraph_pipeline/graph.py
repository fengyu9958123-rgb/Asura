"""Graph construction for the isolated LangGraph image pipeline."""

from __future__ import annotations

from typing import Any

from .nodes import GraphPipelineNodes
from .state import GraphPipelineState


def build_graph(nodes: GraphPipelineNodes, *, resume: bool = False) -> Any:
    """Build a LangGraph StateGraph.

    Import LangGraph lazily so the legacy app can start even before the
    experimental dependency is installed.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph pipeline requires installing langgraph and langchain-core") from exc

    graph = StateGraph(GraphPipelineState)
    graph.add_node("load_module", nodes.load_module())
    graph.add_node("image_analysis", nodes.image_analysis())
    graph.add_node("prd_generation", nodes.prd_generation())
    graph.add_node("prd_review", nodes.prd_review())
    graph.add_node("waiting_confirmation", nodes.wait_for_confirmation())
    graph.add_node("confirmation_integrate", nodes.confirmation_integrate())
    graph.add_node("testcase_pipeline", nodes.testcase_pipeline())
    graph.add_node("save_result", nodes.save_result())

    graph.add_edge(START, "load_module")
    if resume:
        graph.add_edge("load_module", "confirmation_integrate")
    else:
        graph.add_edge("load_module", "image_analysis")
        graph.add_edge("image_analysis", "prd_generation")
        graph.add_edge("prd_generation", "prd_review")
        graph.add_conditional_edges(
            "prd_review",
            nodes.route_after_review,
            {
                "waiting": "waiting_confirmation",
                "continue": "confirmation_integrate",
            },
        )
        graph.add_edge("waiting_confirmation", END)
    graph.add_edge("confirmation_integrate", "testcase_pipeline")
    graph.add_edge("testcase_pipeline", "save_result")
    graph.add_edge("save_result", END)
    return graph.compile()
