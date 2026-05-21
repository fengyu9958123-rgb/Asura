"""Graph construction for the isolated testcase LangGraph subgraph."""

from __future__ import annotations

from typing import Any

from .nodes import TestcaseGraphNodes
from .state import TestcaseGraphState


def build_graph(nodes: TestcaseGraphNodes) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph testcase subgraph requires installing langgraph and langchain-core") from exc

    graph = StateGraph(TestcaseGraphState)
    graph.add_node("prepare_agents", nodes.prepare_agents())
    graph.add_node("block_prd", nodes.block_prd())
    graph.add_node("build_knowledge", nodes.build_knowledge())
    graph.add_node("build_context_units", nodes.build_context_units())
    graph.add_node("generate_unit_cases", nodes.generate_unit_cases())
    graph.add_node("merge_cases", nodes.merge_cases())
    graph.add_node("save_result", nodes.save_result())

    graph.add_edge(START, "prepare_agents")
    graph.add_edge("prepare_agents", "block_prd")
    graph.add_edge("block_prd", "build_knowledge")
    graph.add_edge("build_knowledge", "build_context_units")
    graph.add_edge("build_context_units", "generate_unit_cases")
    graph.add_edge("generate_unit_cases", "merge_cases")
    graph.add_edge("merge_cases", "save_result")
    graph.add_edge("save_result", END)
    return graph.compile()
