"""
PRD Knowledge based structured testcase generation pipeline.

Flow:
final PRD -> line-based BLOCK plan -> marked original PRD -> PRD Knowledge LU grouping
-> code-filled LU context -> LU testcase writing.
"""

import json
import logging
import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from services.generation.llm_json_parser import parse_llm_json
from services.generation.llm_response_cleaner import strip_model_reasoning
from services.generation.llm_usage import record_current_agent_call
from services.generation.pipeline_artifact_service import PipelineArtifactService
from services.generation.prd_block_service import (
    build_block_catalog,
    build_numbered_prd,
    blocks_by_id,
    normalize_block_plan,
    parse_prd_blocks,
    render_blocked_prd,
    strip_block_markers,
    validate_block_plan,
    validate_prd_blocks,
)
from services.generation.prd_context_assembler import (
    assemble_context_for_module,
    build_context_units_from_knowledge,
)
from services.generation.prd_knowledge_service import (
    knowledge_to_markdown,
    normalize_prd_knowledge,
    validate_prd_knowledge,
)

logger = logging.getLogger(__name__)

USE_PRD_KNOWLEDGE_QUALITY_REVIEW = False
PUBLIC_TEST_CASE_COLUMNS = [
    "功能模块", "测试场景分类", "用例编号", "用例名称", "前置条件",
    "测试步骤", "预期结果", "优先级", "用例类型",
]


class StructuredTestcasePipeline:
    """Run the PRD Knowledge testcase pipeline."""

    def __init__(self, logging_service=None):
        self.logging_service = logging_service

    def run(
        self,
        *,
        task_id: str,
        final_prd: str,
        task_name: str,
        output_dir: Optional[str],
        agents: Dict[str, Any],
        requirement_notes: str = "",
        testing_notes: str = "",
        notification_service=None,
    ) -> Dict[str, Any]:
        missing_agents = [
            name
            for name in ("prd_block_builder", "prd_knowledge_builder")
            if not agents.get(name)
        ]
        if not agents.get("module_test_case_writer"):
            missing_agents.append("module_test_case_writer")
        if missing_agents:
            raise RuntimeError("PRD Knowledge 流水线缺少必要 agent: " + ", ".join(missing_agents))
        return self._run_prd_knowledge_pipeline(
            task_id=task_id,
            final_prd=final_prd,
            task_name=task_name,
            output_dir=output_dir,
            agents=agents,
            requirement_notes=requirement_notes,
            testing_notes=testing_notes,
            notification_service=notification_service,
        )

    def _run_prd_knowledge_pipeline(
        self,
        *,
        task_id: str,
        final_prd: str,
        task_name: str,
        output_dir: Optional[str],
        agents: Dict[str, Any],
        requirement_notes: str = "",
        testing_notes: str = "",
        notification_service=None,
    ) -> Dict[str, Any]:
        artifacts = PipelineArtifactService(task_id, output_dir)
        logger.info("PRD Knowledge 测试流水线启动: task_id=%s, artifact_dir=%s", task_id, os.path.abspath(artifacts.base_dir))
        artifacts.write_text("00_final_prd.md", final_prd, "final_prd")

        self._notify(notification_service, task_id, "PRD 知识库：结构化分块")
        blocked_prd, block_plan, block_prompt, block_response, raw_block_plan = self._generate_blocked_prd(
            final_prd=final_prd,
            task_name=task_name,
            agent=agents["prd_block_builder"],
        )
        prd_blocks = parse_prd_blocks(blocked_prd)
        prd_blocks_by_id = blocks_by_id(prd_blocks)
        block_validation = [
            *validate_block_plan(block_plan, final_prd),
            *validate_prd_blocks(prd_blocks, final_prd, blocked_prd),
        ]
        artifacts.write_text("prompts/04a_prd_block_builder.prompt.md", block_prompt, "prd_block_builder_prompt")
        artifacts.write_text("responses/04a_prd_block_builder.response.md", block_response, "prd_block_builder_response")
        artifacts.write_json("04a_prd_block_plan.raw.json", raw_block_plan, "prd_block_plan_raw_json")
        artifacts.write_json("04a_prd_block_plan.json", block_plan, "prd_block_plan_json")
        artifacts.write_text("04a_blocked_prd.md", blocked_prd, "blocked_prd_md")
        artifacts.write_json("04a_prd_blocks.json", {"blocks": prd_blocks}, "prd_blocks_json")
        artifacts.write_json("04a_block_validation.json", {"issues": block_validation}, "prd_block_validation")
        self._raise_if_critical_issues(
            block_validation,
            "04a_prd_blocks",
            artifacts,
            "PRD 分块存在关键问题",
        )

        self._notify(notification_service, task_id, "PRD 知识库：构建 LU 分组")
        knowledge, knowledge_prompt, knowledge_response, raw_knowledge = self._generate_prd_knowledge(
            blocked_prd=blocked_prd,
            prd_blocks=prd_blocks,
            block_validation=block_validation,
            agent=agents["prd_knowledge_builder"],
        )
        knowledge_validation = validate_prd_knowledge(knowledge, prd_blocks_by_id)
        artifacts.write_text("prompts/04b_prd_knowledge_builder.prompt.md", knowledge_prompt, "prd_knowledge_builder_prompt")
        artifacts.write_text("responses/04b_prd_knowledge_builder.response.md", knowledge_response, "prd_knowledge_builder_response")
        artifacts.write_json("04b_prd_knowledge.raw.json", raw_knowledge, "prd_knowledge_raw_json")
        artifacts.write_json("04b_prd_knowledge.json", knowledge, "prd_knowledge_json")
        artifacts.write_text("04b_prd_knowledge.md", knowledge_to_markdown(knowledge), "prd_knowledge_md")
        artifacts.write_json("04b_prd_knowledge.validation.json", {"issues": knowledge_validation}, "prd_knowledge_validation")
        self._raise_if_critical_issues(
            knowledge_validation,
            "04b_prd_knowledge",
            artifacts,
            "PRD Knowledge 存在关键问题",
        )

        if (knowledge.get("integration_modules") or []) and not agents.get("integration_test_case_writer"):
            raise RuntimeError("PRD Knowledge 检测到 integration_lu，但缺少 integration_test_case_writer")

        self._notify(notification_service, task_id, "用例生成：按 PRD Knowledge LU 组装上下文")
        context_units = build_context_units_from_knowledge(knowledge)
        artifacts.write_json("05_context_units.json", context_units, "context_units_json")
        artifacts.write_text("05_context_units.md", self._context_units_to_markdown(context_units), "context_units_md")

        unit_results, messages = self._generate_cases_by_knowledge_context(
            final_prd=final_prd,
            testing_notes=testing_notes,
            knowledge=knowledge,
            prd_blocks_by_id=prd_blocks_by_id,
            context_units=context_units,
            writer_agents={
                "normal_lu": agents.get("module_test_case_writer"),
                "integration_lu": agents.get("integration_test_case_writer"),
            },
            artifacts=artifacts,
            notification_service=notification_service,
            task_id=task_id,
        )
        final_cases = self._merge_unit_results(unit_results)
        if not final_cases:
            exc = RuntimeError("PRD Knowledge 流水线完成但未生成任何测试用例")
            self._record_stage_error(artifacts, "07_test_cases_final", "", "", exc)
            artifacts.write_index()
            raise exc
        artifacts.write_json("06_test_cases.by_unit.json", unit_results, "test_cases_by_unit_json")
        artifacts.write_json("06_test_cases.by_package.json", unit_results, "test_cases_by_package_json")
        artifacts.write_json("07_test_cases.before_review.json", final_cases, "test_cases_before_review_json")
        artifacts.write_text("07_test_cases.before_review.md", self._cases_to_markdown(final_cases), "test_cases_before_review_md")

        quality_review = {
            "enabled": False,
            "reason": "PRD Knowledge pipeline skips final testcase quality review; testcase quality is controlled by BLOCK/LU context generation.",
            "actions": [],
            "applied_actions": [],
            "skipped_actions": [],
            "issues": [],
        }
        if USE_PRD_KNOWLEDGE_QUALITY_REVIEW:
            self._notify(notification_service, task_id, "用例质量检查：检查明显问题")
            final_cases, quality_review, quality_prompt, quality_response = self._review_case_quality(
                final_prd=final_prd,
                final_cases=final_cases,
                knowledge=knowledge,
                unit_results=unit_results,
                agent=agents.get("test_case_quality_reviewer"),
                artifacts=artifacts,
            )
            if quality_prompt or quality_response:
                messages.extend([
                    {"role": "user", "content": quality_prompt},
                    {"role": "assistant", "content": quality_response},
                ])
        elif artifacts:
            artifacts.write_json("07a_test_case_quality_review.json", quality_review, "test_case_quality_review_json")
        artifacts.write_json("07a_test_cases.after_quality_review.json", final_cases, "test_cases_after_quality_review_json")
        artifacts.write_text("07a_test_cases.after_quality_review.md", self._cases_to_markdown(final_cases), "test_cases_after_quality_review_md")

        final_cases = self._renumber_cases(final_cases)
        final_cases_md = self._cases_to_markdown(final_cases)
        artifacts.write_json("07_test_cases.final.json", final_cases, "test_cases_final_json")
        artifacts.write_text("07_test_cases.final.md", final_cases_md, "test_cases_final_md")
        artifacts.write_json("06_test_cases.final.json", final_cases, "test_cases_final_json_legacy")
        artifacts.write_text("06_test_cases.final.md", final_cases_md, "test_cases_final_md_legacy")
        artifact_index = artifacts.write_index()

        test_analysis_md = self._build_prd_knowledge_pipeline_analysis(
            block_validation=block_validation,
            knowledge_validation=knowledge_validation,
            knowledge=knowledge,
            context_units=context_units,
            unit_results=unit_results,
            quality_review=quality_review,
        )
        logger.info(
            "PRD Knowledge 测试流水线完成: task_id=%s, blocks=%s, modules=%s, cases=%s",
            task_id,
            len(prd_blocks),
            len(knowledge.get("modules") or []),
            len(final_cases),
        )
        public_context_units = self._strip_internal_source_claim_fields(context_units)
        public_unit_results = self._strip_internal_source_claim_fields(unit_results)
        return {
            "success": True,
            "pipeline_mode": "prd_knowledge",
            "testcases": final_cases,
            "testcases_raw": final_cases_md,
            "test_analysis": test_analysis_md,
            "requirement_split": {"prd_knowledge": knowledge},
            "module_split": {"prd_knowledge": knowledge},
            "requirement_review": {"enabled": False, "reason": "PRD Knowledge pipeline replaces requirement split review."},
            "testcase_duplicate_review": {"enabled": False, "reason": "Merged into test_case_quality_review."},
            "testcase_review": quality_review,
            "test_case_quality_review": quality_review,
            "context_units": public_context_units,
            "test_packages": self._context_units_as_legacy_packages(context_units),
            "package_results": public_unit_results,
            "package_messages": messages,
            "artifact_dir": os.path.abspath(artifacts.base_dir),
            "artifact_index": artifact_index,
            "artifacts": artifacts.index,
            "analysis_prompt": knowledge_prompt,
            "testcase_prompt": "Unit testcase prompts are saved under prompts/test_cases/*.prompt.md",
        }

    # ------------------------------------------------------------------
    # PRD Knowledge generation
    # ------------------------------------------------------------------
    def _generate_blocked_prd(
        self,
        *,
        final_prd: str,
        task_name: str,
        agent: Any,
    ) -> Tuple[str, Dict[str, Any], str, str, Dict[str, Any]]:
        numbered_prd = build_numbered_prd(final_prd)
        prompt = f"""【任务名称】
{task_name}

【带行号最终 PRD】
{numbered_prd}
"""
        response = self._call_agent(agent, prompt)
        parsed = parse_llm_json(response)
        if not isinstance(parsed, dict):
            raise RuntimeError("PRDBlockBuilder did not return a JSON object")
        block_plan = normalize_block_plan(parsed, final_prd)
        blocked_prd = render_blocked_prd(final_prd, block_plan)
        if strip_block_markers(blocked_prd) != final_prd:
            raise RuntimeError("代码渲染的 BLOCK PRD 无法还原最终 PRD 原文")
        return blocked_prd, block_plan, prompt, response, parsed

    def _generate_prd_knowledge(
        self,
        *,
        blocked_prd: str,
        prd_blocks: List[Dict[str, Any]],
        block_validation: List[Dict[str, Any]],
        agent: Any,
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        prompt = f"""【带 BLOCK 标记的原文 PRD】
{blocked_prd}

【BLOCK 结构校验 issues】
{json.dumps(block_validation, ensure_ascii=False, indent=2)}

【任务】
请基于上述带 BLOCK 标记的原文 PRD，把 BLOCK 聚合成少量相对独立、自包含的 LU 子需求单元。
"""
        response = self._call_agent(agent, prompt)
        parsed = parse_llm_json(response)
        if not isinstance(parsed, dict):
            raise RuntimeError("PRDKnowledgeBuilder did not return a JSON object")
        knowledge = normalize_prd_knowledge(parsed, blocks_by_id(prd_blocks))
        return knowledge, prompt, response, parsed

    def _generate_cases_by_knowledge_context(
        self,
        *,
        final_prd: str,
        testing_notes: str,
        knowledge: Dict[str, Any],
        prd_blocks_by_id: Dict[str, Dict[str, Any]],
        context_units: Dict[str, Any],
        writer_agents: Dict[str, Any],
        artifacts: PipelineArtifactService,
        notification_service=None,
        task_id: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        module_by_id = {
            module.get("lu_id"): module
            for module in [
                *(knowledge.get("modules") or []),
                *(knowledge.get("integration_modules") or []),
            ]
            if module.get("lu_id")
        }
        unit_results: List[Dict[str, Any]] = []
        messages: List[Dict[str, str]] = []
        for index, context_unit in enumerate(context_units.get("context_units") or [], 1):
            unit_id = str(context_unit.get("unit_id") or f"LU-{index:03d}")
            safe_unit_id = self._safe_id(unit_id)
            module = module_by_id.get(unit_id)
            if not module:
                continue
            self._notify(notification_service, task_id, f"用例上下文组装：{unit_id} {context_unit.get('unit_name', '')}".strip())
            assembled_context = assemble_context_for_module(module, knowledge, prd_blocks_by_id, final_prd)
            artifacts.write_json(f"contexts/assembled/{safe_unit_id}.context.json", assembled_context, f"{unit_id}_assembled_context_json")
            artifacts.write_text(f"contexts/assembled/{safe_unit_id}.context.md", assembled_context.get("local_requirement_doc_md", ""), f"{unit_id}_assembled_context_md")

            self._notify(notification_service, task_id, f"用例编写：{unit_id} {context_unit.get('unit_name', '')}".strip())
            prompt = self._build_contextual_testcase_prompt(context_unit, assembled_context, testing_notes)
            artifacts.write_text(f"prompts/test_cases/{safe_unit_id}.prompt.md", prompt, f"{unit_id}_prompt")
            response = ""
            try:
                writer_agent = self._select_test_case_writer(context_unit, assembled_context, writer_agents)
                response = self._call_agent_with_stage(writer_agent, prompt, f"testcase_{safe_unit_id}")
                artifacts.write_text(f"responses/test_cases/{safe_unit_id}.response.md", response, f"{unit_id}_response")
                cases = self._extract_test_cases_from_markdown(response)
                cases = self._decorate_unit_cases(context_unit, assembled_context, cases)
                case_validation = []
            except Exception as exc:
                self._record_stage_error(artifacts, f"06_test_cases_{safe_unit_id}", prompt, response, exc)
                raise
            artifacts.write_json(f"test_cases/{safe_unit_id}.cases.json", cases, f"{unit_id}_cases_json")
            artifacts.write_text(f"test_cases/{safe_unit_id}.cases.md", self._cases_to_markdown(cases), f"{unit_id}_cases_md")
            artifacts.write_json(f"test_cases/{safe_unit_id}.validation.json", {"issues": case_validation}, f"{unit_id}_case_validation")
            unit_results.append({
                "package_id": unit_id,
                "unit_id": unit_id,
                "context_unit": context_unit,
                "case_count": len(cases),
                "curated_context": assembled_context,
                "curated_validation": [],
                "case_validation": case_validation,
                "test_cases": cases,
            })
            messages.extend([
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ])
        return unit_results, messages

    def _call_agent_with_stage(self, agent: Any, prompt: str, stage: str) -> str:
        from services.generation.llm_usage import get_current_recorder, usage_context

        recorder = get_current_recorder()
        if recorder is None:
            return self._call_agent(agent, prompt)
        with usage_context(recorder, stage):
            return self._call_agent(agent, prompt)

    def _build_contextual_testcase_prompt(
        self,
        context_unit: Dict[str, Any],
        assembled_context: Dict[str, Any],
        testing_notes: str,
    ) -> str:
        unit_type = str(context_unit.get("unit_type") or assembled_context.get("unit_type") or "normal_lu")
        if unit_type == "integration_lu":
            flow_hint = str(context_unit.get("flow_hint") or assembled_context.get("flow_hint") or "").strip()
            flow_outline = context_unit.get("flow_outline") or assembled_context.get("flow_outline") or []
            excluded_atomic_focus = context_unit.get("excluded_atomic_focus") or assembled_context.get("excluded_atomic_focus") or []
            boundary_lines = [
                f"- 当前 LU：{context_unit.get('unit_id')} {context_unit.get('unit_name')}",
                "- 当前单元类型：integration_lu（跨模块链路 LU）。",
                f"- 覆盖普通 LU：{', '.join(context_unit.get('covered_lu_ids') or []) or '见上下文'}",
                f"- 链路目标：{flow_hint or '见上下文'}",
                f"- 链路骨架：{' -> '.join(flow_outline) if flow_outline else '见上下文'}",
                f"- 排除单点：{'；'.join(excluded_atomic_focus) if excluded_atomic_focus else '见上下文'}",
                "- 只生成围绕这条链路的完整闭环、联动、状态传递、数据一致性、清理或异常收尾用例。",
                "- 不要把 evidence_block_ids 里的单点事实拆成独立功能测试；它们只是链路证据，不是单点功能清单。",
                "- 每条用例必须至少包含 flow_outline 中两个连续阶段的状态或数据传递：前一阶段产生或改变的条件、对象、数据、状态或异常，必须被后一阶段继续使用、影响或校验。",
                "- 如果只验证某一阶段的查询、展示、排序、按钮、枚举、边界或提示，而没有下游传递或闭环断言，不要作为链路用例输出。",
                "- “当前 LU 链路证据 BLOCK”只能支撑链路，不用于单点功能用例。",
                "- 所有事实必须来自当前上下文中的“PRD 原文”BLOCK。",
            ]
        else:
            boundary_lines = [
                f"- 当前 LU：{context_unit.get('unit_id')} {context_unit.get('unit_name')}",
                "- 当前单元类型：normal_lu（普通 LU）。",
                "- 请围绕“当前 LU 主需求 BLOCK”生成完整用例。",
                "- “当前 LU 辅助证据 BLOCK”只能补充字段、枚举、提示文案、状态、边界或流程上下文，不能单独生成用例。",
                "- 不要为其他 LU 生成独立用例。",
                "- 所有事实必须来自当前上下文中的“PRD 原文”BLOCK。",
            ]
        return f"""【用例生成上下文】
{assembled_context.get("local_requirement_doc_md", "")}

【测试补充备注】
{testing_notes or "无"}

【当前 LU 生成边界】
{chr(10).join(boundary_lines)}
"""

    @staticmethod
    def _select_test_case_writer(
        context_unit: Dict[str, Any],
        assembled_context: Dict[str, Any],
        writer_agents: Dict[str, Any],
    ) -> Any:
        unit_type = str(context_unit.get("unit_type") or assembled_context.get("unit_type") or "normal_lu")
        if unit_type == "integration_lu":
            agent = writer_agents.get("integration_lu")
        else:
            agent = writer_agents.get("normal_lu")
        if not agent:
            raise RuntimeError(f"缺少 {unit_type} 对应的测试用例 writer agent")
        return agent

    def _review_case_quality(
        self,
        *,
        final_prd: str,
        final_cases: List[Dict[str, Any]],
        knowledge: Dict[str, Any],
        unit_results: List[Dict[str, Any]],
        agent: Optional[Any],
        artifacts: Optional[PipelineArtifactService] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str, str]:
        if not agent:
            return final_cases, {"enabled": False, "actions": [], "applied_actions": [], "skipped_actions": []}, "", ""
        prompt = self._build_quality_review_prompt(final_prd, final_cases, knowledge, unit_results)
        if artifacts:
            artifacts.write_text("prompts/07a_test_case_quality_review.prompt.md", prompt, "test_case_quality_review_prompt")
        response = ""
        review_result: Dict[str, Any] = {
            "enabled": True,
            "actions": [],
            "applied_actions": [],
            "skipped_actions": [],
            "issues": [],
        }
        try:
            response = self._call_agent(agent, prompt)
            if artifacts:
                artifacts.write_text("responses/07a_test_case_quality_review.response.md", response, "test_case_quality_review_response")
            parsed = parse_llm_json(response)
            if not isinstance(parsed, dict):
                raise RuntimeError("TestCaseQualityReviewer did not return a JSON object")
            actions = parsed.get("actions")
            if not isinstance(actions, list):
                actions = []
            review_result["issues"] = parsed.get("issues") if isinstance(parsed.get("issues"), list) else []
            review_result["actions"] = actions
            updated_cases, apply_report = self._apply_case_review_actions(final_cases, actions, renumber=False)
            review_result.update(apply_report)
            if artifacts:
                artifacts.write_json("07a_test_case_quality_review.json", review_result, "test_case_quality_review_json")
            return updated_cases, review_result, prompt, response
        except Exception as exc:
            fallback_result = {
                **review_result,
                "actions": [],
                "error": str(exc),
                "applied_actions": [],
                "skipped_actions": [],
            }
            if artifacts:
                self._record_stage_error(artifacts, "07a_test_case_quality_review", prompt, response, exc)
                artifacts.write_json("07a_test_case_quality_review.json", fallback_result, "test_case_quality_review_json")
            return final_cases, fallback_result, prompt, response

    def _build_quality_review_prompt(
        self,
        final_prd: str,
        final_cases: List[Dict[str, Any]],
        knowledge: Dict[str, Any],
        unit_results: List[Dict[str, Any]],
    ) -> str:
        compact_cases = [self._case_for_review(case) for case in final_cases]
        coverage = self._build_case_coverage_matrix(final_cases, knowledge)
        context_summary = []
        for result in unit_results:
            context = result.get("curated_context") or {}
            context_summary.append({
                "unit_id": result.get("unit_id"),
                "unit_type": context.get("unit_type"),
                "case_count": result.get("case_count"),
                "block_ids": context.get("requirement_ids") or [],
                "support_block_ids": context.get("supporting_requirement_ids") or [],
                "flow_hint": context.get("flow_hint") or "",
                "flow_outline": context.get("flow_outline") or [],
                "excluded_atomic_focus": context.get("excluded_atomic_focus") or [],
                "global_block_ids": [
                    block.get("block_id")
                    for block in context.get("global_blocks") or []
                    if block.get("block_id")
                ],
                "blocks": [
                    {
                        "block_id": block.get("block_id"),
                        "type": block.get("type"),
                        "title": block.get("title"),
                    }
                    for block in [
                        *(context.get("global_blocks") or []),
                        *(context.get("primary_blocks") or []),
                        *(context.get("support_blocks") or []),
                    ]
                    if block.get("block_id")
                ],
            })
        knowledge_summary = {
            "global_summary": knowledge.get("global_summary", ""),
            "global_block_ids": knowledge.get("global_block_ids") or [],
            "support_only_blocks": knowledge.get("support_only_blocks") or [],
            "modules": [
                {
                    "lu_id": module.get("lu_id"),
                    "unit_type": module.get("unit_type"),
                    "title": module.get("title"),
                    "summary": module.get("summary"),
                    "primary_block_ids": module.get("primary_block_ids") or module.get("block_ids") or [],
                    "support_block_ids": module.get("support_block_ids") or [],
                    "evidence_block_ids": module.get("evidence_block_ids") or [],
                    "flow_hint": module.get("flow_hint") or module.get("integration_focus") or "",
                    "flow_outline": module.get("flow_outline") or [],
                    "excluded_atomic_focus": module.get("excluded_atomic_focus") or [],
                    "block_ids": module.get("evidence_block_ids") or module.get("primary_block_ids") or module.get("block_ids") or [],
                }
                for module in knowledge.get("modules") or []
            ],
            "integration_modules": [
                {
                    "lu_id": module.get("lu_id"),
                    "unit_type": module.get("unit_type"),
                    "title": module.get("title"),
                    "summary": module.get("summary"),
                    "covered_lu_ids": module.get("covered_lu_ids") or [],
                    "evidence_block_ids": module.get("evidence_block_ids") or [],
                    "support_block_ids": module.get("support_block_ids") or [],
                    "flow_hint": module.get("flow_hint") or module.get("integration_focus") or "",
                    "flow_outline": module.get("flow_outline") or [],
                    "excluded_atomic_focus": module.get("excluded_atomic_focus") or [],
                }
                for module in knowledge.get("integration_modules") or []
            ],
        }
        return f"""【PRD Knowledge LU/BLOCK 摘要】
{json.dumps(knowledge_summary, ensure_ascii=False, indent=2)}

【最终 PRD 原文】
{final_prd}

【上下文与覆盖矩阵】
{json.dumps({"contexts": context_summary, "coverage": coverage}, ensure_ascii=False, indent=2)}

【当前测试用例 JSON】
{json.dumps(compact_cases, ensure_ascii=False, indent=2)}
"""

    def _build_case_coverage_matrix(
        self,
        final_cases: List[Dict[str, Any]],
        knowledge: Dict[str, Any],
    ) -> Dict[str, Any]:
        package_ids: List[str] = []
        for module in [
            *(knowledge.get("modules") or []),
            *(knowledge.get("integration_modules") or []),
        ]:
            module_id = str(module.get("lu_id") or "")
            if not module_id:
                continue
            package_ids.append(module_id)
        matrix = {
            "packages": {package_id: [] for package_id in package_ids},
        }
        for case in final_cases or []:
            case_id = str(case.get("用例编号") or "")
            match = re.match(r"^((?:LU|INT)-\d{3})-TC\d{3}$", case_id)
            package_id = match.group(1) if match else ""
            if package_id and package_id in matrix["packages"]:
                matrix["packages"].setdefault(package_id, []).append(case_id)
        return matrix

    def _build_prd_knowledge_pipeline_analysis(
        self,
        *,
        block_validation: List[Dict[str, Any]],
        knowledge_validation: List[Dict[str, Any]],
        knowledge: Dict[str, Any],
        context_units: Dict[str, Any],
        unit_results: List[Dict[str, Any]],
        quality_review: Dict[str, Any],
    ) -> str:
        lines = ["# PRD Knowledge 测试生成分析", ""]
        lines.append("## PRD 分块")
        lines.append(f"- block_issues: {len(block_validation or [])}")
        lines.append("")
        lines.append("## PRD Knowledge")
        lines.append(f"- knowledge_issues: {len(knowledge_validation or [])}")
        lines.append(f"- support_only_blocks: {len(knowledge.get('support_only_blocks') or knowledge.get('global_block_ids') or [])}")
        lines.append(f"- modules: {len(knowledge.get('modules') or [])}")
        lines.append(f"- warnings: {len(knowledge.get('warnings') or [])}")
        lines.append("")
        lines.append("## 用例生成单元")
        for unit in context_units.get("context_units") or []:
            lines.append(f"- {unit.get('unit_id')} {unit.get('unit_name')}: {unit.get('unit_boundary', '')}")
        lines.append("")
        lines.append("## 用例生成")
        for result in unit_results:
            lines.append(f"- {result.get('unit_id')}: cases={result.get('case_count', 0)}")
        lines.append("")
        lines.append("## 用例明显问题审查")
        lines.append(f"- enabled: {bool(quality_review.get('enabled'))}")
        lines.append(f"- issues: {len(quality_review.get('issues') or [])}")
        lines.append(f"- actions: {len(quality_review.get('actions') or [])}")
        lines.append(f"- applied: {len(quality_review.get('applied_actions') or [])}")
        lines.append(f"- skipped: {len(quality_review.get('skipped_actions') or [])}")
        if quality_review.get("error"):
            lines.append(f"- error: {quality_review.get('error')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Case parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _case_for_review(case: Dict[str, Any]) -> Dict[str, Any]:
        return {header: case.get(header, "") for header in PUBLIC_TEST_CASE_COLUMNS}

    def _decorate_unit_cases(
        self,
        context_unit: Dict[str, Any],
        local_requirement_context: Dict[str, Any],
        cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        unit_id = str(context_unit.get("unit_id") or local_requirement_context.get("unit_id") or "LU")
        decorated: List[Dict[str, Any]] = []
        for index, case in enumerate(cases, 1):
            normalized = self._public_case(case)
            normalized["用例编号"] = f"{unit_id}-TC{index:03d}"
            decorated.append(normalized)
        return decorated

    def _extract_test_cases_from_markdown(self, markdown_content: str) -> List[Dict[str, Any]]:
        markdown_content = self._strip_thinking_blocks(markdown_content)
        lines = markdown_content.split("\n")
        required_columns = ["功能模块", "用例编号", "测试步骤", "预期结果"]
        headers: List[str] = []
        testcases: List[Dict[str, Any]] = []
        in_table = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            if not in_table and "|" in line and sum(1 for col in required_columns if col in line) >= 2:
                headers = [cell.strip() for cell in line.split("|")[1:-1]]
                in_table = True
                continue
            if in_table and self._is_separator_line(line):
                continue
            if in_table and line.startswith("|") and line.endswith("|"):
                cells = [cell.strip() for cell in line.split("|")[1:-1]]
                cells = self._normalize_markdown_table_cells(headers, cells)
                row = {header: cells[idx] if idx < len(cells) else "" for idx, header in enumerate(headers)}
                if row.get("用例编号") and row.get("用例名称"):
                    testcases.append(row)
                continue
            if in_table and not line.startswith("|"):
                break
        return testcases

    @staticmethod
    def _is_separator_line(line: str) -> bool:
        """Return whether a Markdown table row is the header separator."""
        text = str(line or "").strip()
        if not text.startswith("|") or not text.endswith("|"):
            return False
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        if not cells:
            return False
        return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

    @staticmethod
    def _normalize_markdown_table_cells(headers: List[str], cells: List[str]) -> List[str]:
        if not headers or len(cells) <= len(headers):
            return cells
        normalized = list(cells)
        if len(normalized) == len(headers) + 1 and "用例名称" in headers and "前置条件" in headers:
            extra_index = headers.index("用例名称") + 1
            if extra_index < len(normalized) and re.fullmatch(r"\d{1,4}", normalized[extra_index].strip()):
                normalized.pop(extra_index)
        if len(normalized) <= len(headers):
            return normalized
        normalized = StructuredTestcasePipeline._repair_shifted_case_columns(headers, normalized)
        if len(normalized) <= len(headers):
            return normalized
        return normalized[:len(headers)]

    @staticmethod
    def _repair_shifted_case_columns(headers: List[str], cells: List[str]) -> List[str]:
        required = ["预期结果", "优先级", "用例类型"]
        if not all(header in headers for header in required):
            return cells
        priority_index = headers.index("优先级")
        type_index = headers.index("用例类型")

        priority_pattern = re.compile(r"^P[0-3]$", re.IGNORECASE)
        normalized = list(cells)
        while len(normalized) > len(headers):
            priority_value = str(normalized[priority_index]).strip()
            type_value = str(normalized[type_index]).strip()
            if priority_pattern.fullmatch(priority_value) and type_value:
                break
            if priority_pattern.fullmatch(type_value):
                normalized[priority_index - 1] = "<br>".join([
                    str(normalized[priority_index - 1]).strip(),
                    str(normalized[priority_index]).strip(),
                ]).strip("<br>")
                del normalized[priority_index]
                continue
            break
        return normalized

    @staticmethod
    def _strip_thinking_blocks(content: str) -> str:
        return str(strip_model_reasoning(content or "")).strip()

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        text = str(strip_model_reasoning(content or "")).strip()
        match = re.fullmatch(r"```(?:markdown|md|text)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _compact_text(content: Any, max_chars: int = 220) -> str:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values or []:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _public_case(case: Dict[str, Any]) -> Dict[str, Any]:
        return {
            header: str(case.get(header) or "").strip()
            for header in PUBLIC_TEST_CASE_COLUMNS
        }

    # ------------------------------------------------------------------
    # Formatting and compatibility helpers
    # ------------------------------------------------------------------
    def _context_units_to_markdown(self, context_units: Dict[str, Any]) -> str:
        lines = ["# Context Units", "", context_units.get("unit_summary", ""), ""]
        for unit in context_units.get("context_units") or []:
            lines.append(f"## {unit.get('unit_id')} {unit.get('unit_name', '')}")
            lines.append(f"- unit_type: {unit.get('unit_type', '')}")
            if unit.get("flow_hint"):
                lines.append(f"- flow_hint: {unit.get('flow_hint')}")
            if unit.get("flow_outline"):
                lines.append(f"- flow_outline: {' -> '.join(unit.get('flow_outline') or [])}")
            if unit.get("excluded_atomic_focus"):
                lines.append(f"- excluded_atomic_focus: {'；'.join(unit.get('excluded_atomic_focus') or [])}")
            lines.append(f"- evidence_blocks: {', '.join(unit.get('requirement_ids') or [])}")
            if unit.get("supporting_requirement_ids"):
                lines.append(f"- support_blocks: {', '.join(unit.get('supporting_requirement_ids') or [])}")
            if unit.get("source_claim_ids"):
                lines.append(f"- internal_source_claims: {', '.join(unit.get('source_claim_ids') or [])}")
            if unit.get("unit_boundary"):
                lines.append(f"- boundary: {unit.get('unit_boundary')}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _cases_to_markdown(cases: List[Dict[str, Any]]) -> str:
        headers = PUBLIC_TEST_CASE_COLUMNS
        lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        for case in cases:
            row = [str(case.get(header, "")).replace("\n", "<br>") for header in headers]
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines) + "\n"

    def _merge_unit_results(self, unit_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for result in unit_results:
            for case in result.get("test_cases") or []:
                merged.append(self._public_case(case))
        return merged

    def _apply_case_review_actions(
        self,
        cases: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
        *,
        renumber: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        current = [dict(case) for case in cases]
        report = {
            "applied_actions": [],
            "skipped_actions": [],
            "flagged_issues": [],
        }
        for index, action in enumerate(actions or [], 1):
            if not isinstance(action, dict):
                self._skip_case_action(report, index, action, "action is not an object")
                continue
            action_type = str(action.get("type") or "").strip().lower()
            try:
                if action_type == "add":
                    current = self._apply_case_add(current, action, report, index)
                elif action_type == "update":
                    current = self._apply_case_update(current, action, report, index)
                elif action_type == "delete":
                    current = self._apply_case_delete(current, action, report, index)
                elif action_type == "merge":
                    current = self._apply_case_merge(current, action, report, index)
                elif action_type == "split":
                    current = self._apply_case_split(current, action, report, index)
                elif action_type == "flag":
                    report["flagged_issues"].append({
                        "index": index,
                        "case_id": action.get("case_id", ""),
                        "issue": action.get("issue", ""),
                        "reason": action.get("reason", ""),
                    })
                else:
                    self._skip_case_action(report, index, action, f"unsupported action type: {action_type}")
            except Exception as exc:
                self._skip_case_action(report, index, action, str(exc))
        return (self._renumber_cases(current) if renumber else current), report

    def _apply_case_add(
        self,
        cases: List[Dict[str, Any]],
        action: Dict[str, Any],
        report: Dict[str, Any],
        index: int,
    ) -> List[Dict[str, Any]]:
        new_case = self._normalize_review_case(action.get("case"))
        if not new_case:
            self._skip_case_action(report, index, action, "add.case is invalid")
            return cases
        insert_at = len(cases)
        insert_after = str(action.get("insert_after_case_id") or "").strip()
        if insert_after:
            position = self._find_case_index(cases, insert_after)
            if position >= 0:
                insert_at = position + 1
        else:
            nearby = self._find_nearby_case_for_insert(cases, new_case)
            if nearby >= 0:
                insert_at = nearby + 1
        cases.insert(insert_at, new_case)
        self._record_applied_case_action(report, index, action, "add", [new_case.get("用例名称", "")])
        return cases

    def _apply_case_update(
        self,
        cases: List[Dict[str, Any]],
        action: Dict[str, Any],
        report: Dict[str, Any],
        index: int,
    ) -> List[Dict[str, Any]]:
        case_id = str(action.get("case_id") or "").strip()
        position = self._find_case_index(cases, case_id)
        if position < 0:
            self._skip_case_action(report, index, action, f"case not found: {case_id}")
            return cases
        fields = self._allowed_case_fields(action.get("fields"))
        if not fields:
            self._skip_case_action(report, index, action, "update.fields is empty")
            return cases
        cases[position].update(fields)
        self._record_applied_case_action(report, index, action, "update", [case_id])
        return cases

    def _apply_case_delete(
        self,
        cases: List[Dict[str, Any]],
        action: Dict[str, Any],
        report: Dict[str, Any],
        index: int,
    ) -> List[Dict[str, Any]]:
        case_id = str(action.get("case_id") or "").strip()
        position = self._find_case_index(cases, case_id)
        if position < 0:
            self._skip_case_action(report, index, action, f"case not found: {case_id}")
            return cases
        del cases[position]
        self._record_applied_case_action(report, index, action, "delete", [case_id])
        return cases

    def _apply_case_merge(
        self,
        cases: List[Dict[str, Any]],
        action: Dict[str, Any],
        report: Dict[str, Any],
        index: int,
    ) -> List[Dict[str, Any]]:
        target_id = str(action.get("target_case_id") or "").strip()
        target_position = self._find_case_index(cases, target_id)
        if target_position < 0:
            self._skip_case_action(report, index, action, f"target case not found: {target_id}")
            return cases
        source_ids = [str(item).strip() for item in action.get("source_case_ids") or [] if str(item).strip()]
        source_positions = [self._find_case_index(cases, case_id) for case_id in source_ids]
        missing = [case_id for case_id, pos in zip(source_ids, source_positions) if pos < 0]
        if missing:
            self._skip_case_action(report, index, action, f"source case not found: {', '.join(missing)}")
            return cases
        fields = self._allowed_case_fields(action.get("fields"))
        if fields:
            cases[target_position].update(fields)
        remove_positions = sorted({pos for pos in source_positions if pos >= 0 and pos != target_position}, reverse=True)
        for pos in remove_positions:
            del cases[pos]
        self._record_applied_case_action(
            report,
            index,
            action,
            "merge",
            self._dedupe_preserve_order([target_id, *source_ids]),
        )
        return cases

    def _apply_case_split(
        self,
        cases: List[Dict[str, Any]],
        action: Dict[str, Any],
        report: Dict[str, Any],
        index: int,
    ) -> List[Dict[str, Any]]:
        source_id = str(action.get("source_case_id") or "").strip()
        position = self._find_case_index(cases, source_id)
        if position < 0:
            self._skip_case_action(report, index, action, f"source case not found: {source_id}")
            return cases
        replacements = []
        for raw_case in action.get("replacement_cases") or []:
            normalized = self._normalize_review_case(raw_case)
            if normalized:
                replacements.append(normalized)
        if not replacements:
            self._skip_case_action(report, index, action, "split.replacement_cases is empty")
            return cases
        self._record_applied_case_action(report, index, action, "split", [source_id])
        return [
            *cases[:position],
            *replacements,
            *cases[position + 1:],
        ]

    @staticmethod
    def _allowed_case_fields(fields: Any) -> Dict[str, str]:
        if not isinstance(fields, dict):
            return {}
        allowed = {
            "功能模块", "测试场景分类", "用例名称", "前置条件", "测试步骤",
            "预期结果", "优先级", "用例类型",
        }
        return {
            key: str(value).strip()
            for key, value in fields.items()
            if key in allowed and str(value).strip()
        }

    @classmethod
    def _normalize_review_case(cls, raw_case: Any) -> Dict[str, Any]:
        if not isinstance(raw_case, dict):
            return {}
        required = ["功能模块", "测试场景分类", "用例名称", "测试步骤", "预期结果", "优先级", "用例类型"]
        normalized = cls._allowed_case_fields(raw_case)
        if any(not normalized.get(field) for field in required):
            return {}
        normalized.setdefault("前置条件", str(raw_case.get("前置条件") or "").strip())
        return normalized

    @staticmethod
    def _find_case_index(cases: List[Dict[str, Any]], case_id: str) -> int:
        for index, case in enumerate(cases):
            if str(case.get("用例编号") or "").strip() == case_id:
                return index
        return -1

    @staticmethod
    def _find_nearby_case_for_insert(cases: List[Dict[str, Any]], new_case: Dict[str, Any]) -> int:
        module = str(new_case.get("功能模块") or "").strip()
        scenario = str(new_case.get("测试场景分类") or "").strip()
        if module:
            for index in range(len(cases) - 1, -1, -1):
                if str(cases[index].get("功能模块") or "").strip() == module:
                    return index
        if scenario:
            for index in range(len(cases) - 1, -1, -1):
                if str(cases[index].get("测试场景分类") or "").strip() == scenario:
                    return index
        return len(cases) - 1 if cases else -1

    @staticmethod
    def _skip_case_action(report: Dict[str, Any], index: int, action: Any, reason: str) -> None:
        report.setdefault("skipped_actions", []).append({
            "index": index,
            "type": action.get("type", "") if isinstance(action, dict) else "",
            "reason": reason,
            "action": action,
        })

    @staticmethod
    def _record_applied_case_action(
        report: Dict[str, Any],
        index: int,
        action: Dict[str, Any],
        action_type: str,
        case_ids: List[str],
    ) -> None:
        report.setdefault("applied_actions", []).append({
            "index": index,
            "type": action_type,
            "case_ids": case_ids,
            "reason": action.get("reason", ""),
        })

    @staticmethod
    def _renumber_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        renumbered: List[Dict[str, Any]] = []
        for index, case in enumerate(cases, 1):
            normalized = StructuredTestcasePipeline._public_case(case)
            if re.fullmatch(r"(?:LU|INT)-\d{3}-TC\d{3}", str(normalized.get("用例编号") or "").strip()):
                normalized["用例编号"] = str(normalized.get("用例编号") or "").strip()
            else:
                normalized["用例编号"] = f"TC{index:03d}"
            renumbered.append(normalized)
        return renumbered

    def _context_units_as_legacy_packages(self, context_units: Dict[str, Any]) -> Dict[str, Any]:
        packages = []
        for unit in context_units.get("context_units") or []:
            packages.append({
                "package_id": unit.get("unit_id"),
                "package_name": unit.get("unit_name"),
                "type": unit.get("unit_type") or unit.get("source_type"),
                "source_groups": unit.get("related_module_ids") or [],
                "source_flow": unit.get("source_id") if (unit.get("source_type") == "cross_module_flow" or unit.get("unit_type") == "flow") else "",
                "included_requirements": unit.get("requirement_ids") or [],
                "supporting_requirements": unit.get("supporting_requirement_ids") or [],
                "included_relations": [],
                "test_focus": [unit.get("unit_boundary")] if unit.get("unit_boundary") else [],
            })
        return {"plan_summary": "兼容字段：当前版本按 LU 局部需求单元生成。", "test_packages": packages}

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    def _call_agent(self, agent: Any, prompt: str) -> str:
        if not agent:
            raise RuntimeError("required agent is not available")
        responses_config = self._get_openai_responses_config(agent)
        if responses_config:
            return self._call_openai_responses(agent, prompt, responses_config)
        before_usage = self._agent_usage_snapshot(agent)
        response = agent.generate_reply(messages=[{"role": "user", "content": prompt}])
        if not response:
            raise RuntimeError(f"{getattr(agent, 'name', 'agent')} returned empty response")
        response_text = str(strip_model_reasoning(response))
        usage = self._agent_usage_delta(agent, before_usage)
        record_current_agent_call(
            agent=agent,
            prompt=prompt,
            response=response_text,
            usage=usage,
            estimated=usage is None,
        )
        return response_text

    def _get_openai_responses_config(self, agent: Any) -> Optional[Dict[str, Any]]:
        config_list = getattr(getattr(agent, "llm_config", None), "get", lambda *_: None)("config_list")
        if not isinstance(config_list, list):
            return None
        for config in config_list:
            if isinstance(config, dict) and config.get("api") == "openai-responses":
                return config
        return None

    def _call_openai_responses(self, agent: Any, prompt: str, config: Dict[str, Any]) -> str:
        api_key = config.get("api_key")
        base_url = str(config.get("base_url") or "").rstrip("/")
        model = config.get("model")
        if not api_key or not base_url or not model:
            raise RuntimeError("openai-responses config requires api_key, base_url and model")
        url = f"{base_url}/responses" if not base_url.endswith("/responses") else base_url
        system_message = str(getattr(agent, "system_message", "") or "").strip()
        input_items: List[Dict[str, Any]] = []
        if system_message:
            input_items.append({
                "role": "developer",
                "content": [{"type": "input_text", "text": system_message}],
            })
        input_items.append({
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        })
        response_result = self._post_openai_responses_stream(
            url=url,
            api_key=api_key,
            body={
                "model": model,
                "stream": True,
                "input": input_items,
            },
        )
        response_text = response_result.get("text", "") if isinstance(response_result, dict) else str(response_result or "")
        response_text = str(strip_model_reasoning(response_text or "")).strip()
        if not response_text:
            raise RuntimeError(f"{getattr(agent, 'name', 'agent')} returned empty openai-responses output")
        usage = response_result.get("usage") if isinstance(response_result, dict) else None
        record_current_agent_call(
            agent=agent,
            prompt=prompt,
            response=response_text,
            usage=usage,
            estimated=usage is None,
            metadata={"api": "openai-responses"},
        )
        return response_text

    def _post_openai_responses_stream(self, *, url: str, api_key: str, body: Dict[str, Any]) -> Dict[str, Any]:
        max_attempts = 3
        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._post_openai_responses_stream_once(url=url, api_key=api_key, body=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                delay = min(2 ** (attempt - 1), 4)
                logger.warning(
                    "openai-responses transport error, retrying: attempt=%s/%s, error=%s",
                    attempt,
                    max_attempts,
                    exc,
                )
                time.sleep(delay)
        if last_error:
            raise last_error
        raise RuntimeError("openai-responses request failed without response")

    def _post_openai_responses_stream_once(self, *, url: str, api_key: str, body: Dict[str, Any]) -> Dict[str, Any]:
        text_parts: List[str] = []
        final_messages: List[str] = []
        usage: Dict[str, Any] = {}
        state = {"data_lines": []}

        def flush_event() -> None:
            if not state["data_lines"]:
                return
            raw = "\n".join(state["data_lines"])
            state["data_lines"] = []
            try:
                payload = json.loads(raw)
            except Exception:
                return
            event_type = payload.get("type")
            if event_type == "response.output_text.delta":
                text_parts.append(str(payload.get("delta") or ""))
                return
            if event_type == "response.output_item.done":
                self._collect_response_message_text(payload.get("item") or {}, final_messages)
                return
            if event_type == "response.completed":
                response = payload.get("response") or {}
                for item in response.get("output") or []:
                    if isinstance(item, dict):
                        self._collect_response_message_text(item, final_messages)
                usage.update(self._extract_openai_responses_usage(response))
                return
            if event_type == "response.failed":
                error = (payload.get("response") or {}).get("error") or payload.get("error") or {}
                raise RuntimeError(f"openai-responses failed: {error}")

        with httpx.Client(timeout=600, trust_env=True) as client:
            with client.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f"openai-responses HTTP {response.status_code}: {response.text[:1000]}")
                for line in response.iter_lines():
                    if line == "":
                        flush_event()
                    elif line.startswith("data:"):
                        state["data_lines"].append(line[5:].strip())
                flush_event()

        return {
            "text": "".join(text_parts).strip() or "".join(final_messages).strip(),
            "usage": usage or None,
        }

    @staticmethod
    def _extract_openai_responses_usage(response: Dict[str, Any]) -> Dict[str, Any]:
        raw_usage = response.get("usage") if isinstance(response, dict) else None
        if not isinstance(raw_usage, dict):
            return {}
        input_tokens = raw_usage.get("input_tokens") or raw_usage.get("prompt_tokens") or 0
        output_tokens = raw_usage.get("output_tokens") or raw_usage.get("completion_tokens") or 0
        total_tokens = raw_usage.get("total_tokens") or int(input_tokens or 0) + int(output_tokens or 0)
        return {
            "model": response.get("model") or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "raw": raw_usage,
        }

    @staticmethod
    def _agent_usage_snapshot(agent: Any) -> Dict[str, Dict[str, Any]]:
        usage = None
        try:
            usage = agent.get_actual_usage()
        except Exception:
            usage = None
        return StructuredTestcasePipeline._normalize_usage_summary(usage)

    @staticmethod
    def _agent_usage_delta(agent: Any, before: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            after = StructuredTestcasePipeline._normalize_usage_summary(agent.get_actual_usage())
        except Exception:
            return None
        best_model = ""
        best_delta = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_input_tokens": 0,
        }
        for model, values in after.items():
            previous = before.get(model, {})
            delta = {
                "prompt_tokens": max(0, int(values.get("prompt_tokens") or 0) - int(previous.get("prompt_tokens") or 0)),
                "completion_tokens": max(0, int(values.get("completion_tokens") or 0) - int(previous.get("completion_tokens") or 0)),
                "total_tokens": max(0, int(values.get("total_tokens") or 0) - int(previous.get("total_tokens") or 0)),
                "cached_input_tokens": max(
                    0,
                    int(values.get("cached_input_tokens") or 0)
                    - int(previous.get("cached_input_tokens") or 0),
                ),
            }
            if delta["total_tokens"] > best_delta["total_tokens"]:
                best_model = model
                best_delta = delta
        if best_delta["total_tokens"] <= 0 and best_delta["prompt_tokens"] <= 0 and best_delta["completion_tokens"] <= 0:
            return None
        return {
            "model": best_model,
            "prompt_tokens": best_delta["prompt_tokens"],
            "completion_tokens": best_delta["completion_tokens"],
            "total_tokens": best_delta["total_tokens"] or best_delta["prompt_tokens"] + best_delta["completion_tokens"],
            "cached_input_tokens": best_delta["cached_input_tokens"],
        }

    @staticmethod
    def _normalize_usage_summary(summary: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(summary, dict):
            return {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for model, values in summary.items():
            if model == "total_cost" or not isinstance(values, dict):
                continue
            raw_details = values.get("prompt_tokens_details") or values.get("input_tokens_details") or {}
            cached_input_tokens = 0
            if isinstance(raw_details, dict):
                cached_input_tokens = int(raw_details.get("cached_tokens") or 0)
            normalized[str(model)] = {
                "prompt_tokens": int(values.get("prompt_tokens") or 0),
                "completion_tokens": int(values.get("completion_tokens") or 0),
                "total_tokens": int(values.get("total_tokens") or 0),
                "cached_input_tokens": int(values.get("cached_input_tokens") or cached_input_tokens or 0),
            }
        return normalized

    def _collect_response_message_text(self, item: Dict[str, Any], result: List[str]) -> None:
        if item.get("type") != "message":
            return
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                result.append(str(content.get("text") or ""))

    def _raise_if_critical_issues(
        self,
        issues: List[Dict[str, Any]],
        stage: str,
        artifacts: Optional[PipelineArtifactService],
        message: str,
    ) -> None:
        critical_issues = [issue for issue in issues or [] if str(issue.get("severity") or "").lower() == "critical"]
        if not critical_issues:
            return
        exc = RuntimeError(f"{message}: {self._summarize_issues(critical_issues)}")
        self._record_stage_error(artifacts, stage, "", "", exc)
        raise exc

    @staticmethod
    def _summarize_issues(issues: List[Dict[str, Any]]) -> str:
        messages: List[str] = []
        for issue in issues or []:
            detail = str(issue.get("message") or issue.get("detail") or "").strip()
            code = str(issue.get("code") or "").strip()
            messages.append(detail or code or str(issue))
        return " | ".join(messages[:5])

    @staticmethod
    def _strip_internal_source_claim_fields(value: Any) -> Any:
        internal_keys = {"source_claim_id", "source_claim_ids", "source_claims"}
        if isinstance(value, dict):
            return {
                key: StructuredTestcasePipeline._strip_internal_source_claim_fields(item)
                for key, item in value.items()
                if key not in internal_keys
            }
        if isinstance(value, list):
            return [StructuredTestcasePipeline._strip_internal_source_claim_fields(item) for item in value]
        return value

    def _record_stage_error(
        self,
        artifacts: Optional[PipelineArtifactService],
        stage: str,
        prompt: str,
        response: str,
        error: Exception,
    ) -> None:
        logger.exception("结构化流水线阶段失败: stage=%s, error=%s", stage, error)
        if not artifacts:
            return
        artifacts.write_json(
            f"errors/{stage}.error.json",
            {
                "stage": stage,
                "error_type": type(error).__name__,
                "error": str(error),
                "prompt_length": len(prompt or ""),
                "response_length": len(response or ""),
                "traceback": traceback.format_exc(),
            },
            f"{stage}_error",
        )
        artifacts.write_index()

    @staticmethod
    def _safe_id(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value))

    def _notify(self, notification_service, task_id: str, message: str) -> None:
        if not notification_service:
            return
        try:
            notification_service.notify_log(task_id, message)
        except Exception:
            logger.debug("notify_log failed", exc_info=True)
