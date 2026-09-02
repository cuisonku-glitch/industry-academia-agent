"""Build an evidence-gated enterprise solution without inventing requirements."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "enterprise_solution_v1"
SOURCE_TYPES = frozenset(
    {"enterprise_confirmed", "paper_evidence", "system_suggestion", "unknown"}
)

CAPABILITY_PROBLEM_HINTS: dict[str, tuple[str, ...]] = {
    "高灵敏度": ("灵敏度", "探测能力"),
    "低成本": ("成本",),
    "大面积": ("大面积", "面积"),
    "高分辨率": ("分辨率", "图像模糊"),
    "高稳定性": ("稳定性", "衰减", "基线漂移", "寿命"),
    "快速响应": ("响应", "实时", "高速"),
    "低电压": ("电压", "偏压"),
}

METRIC_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "X射线能量": ("X射线", "探测", "成像"),
    "检测精度": ("同心度", "测量", "检测"),
    "检测频率": ("在线", "快速", "检测"),
    "检测可靠性": ("稳定", "冗余", "检测"),
    "缺陷识别精度": ("缺陷", "智能检测"),
    "最小可检测缺陷尺寸": ("缺陷", "智能检测"),
    "检测速度": ("在线", "快速", "智能检测"),
    "灵敏度": ("灵敏度", "探测"),
    "检测限": ("检测限", "探测"),
    "分辨率": ("分辨率", "成像"),
    "成本": ("成本",),
    "面积": ("面积", "尺寸", "规模"),
    "尺寸": ("面积", "尺寸", "规模"),
    "电压": ("电压", "偏压", "自驱动"),
    "响应时间": ("响应", "实时", "高速"),
    "稳定性": ("稳定", "寿命"),
    "寿命": ("稳定", "寿命"),
}

TRANSFER_WEIGHTS = {
    "demand_fit": 0.35,
    "evidence_strength": 0.35,
    "engineering_maturity": 0.15,
    "landing_constraints": 0.15,
}


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        identity = "".join(cleaned.casefold().split())
        if cleaned and identity not in seen:
            seen.add(identity)
            result.append(cleaned)
    return result


def _phrases_for(
    profile: dict[str, Any], field: str, value: str | None = None
) -> list[str]:
    return _unique_strings(
        phrase
        for item in profile.get("evidence_map", [])
        if item.get("field") == field and (value is None or item.get("value") == value)
        for phrase in item.get("matched_phrases", [])
    )


def build_clarification(profile: dict[str, Any]) -> dict[str, Any]:
    """Generate explicit questions for unknown or under-specified request fields."""
    questions: list[dict[str, Any]] = []

    def add(
        field: str,
        question: str,
        reason: str,
        severity: str,
    ) -> None:
        questions.append(
            {
                "question_id": f"Q{len(questions) + 1:02d}",
                "field": field,
                "question": question,
                "reason": reason,
                "severity": severity,
                "source_type": "unknown",
            }
        )

    if profile.get("industry") == "未明确":
        add(
            "industry",
            "该产品具体用于哪个行业和现场场景？",
            "行业会改变测试与合规边界。",
            "blocking",
        )
    if profile.get("product") == "未明确":
        add(
            "product",
            "当前要开发或改造的产品/系统是什么？",
            "需要确定方案接口和交付对象。",
            "blocking",
        )
    if not profile.get("technical_problems"):
        add(
            "technical_problems",
            "当前已经观察到的具体故障或性能差距是什么？",
            "期望能力不能自动当作现存问题。",
            "important",
        )
    if not profile.get("required_capabilities"):
        add(
            "required_capabilities",
            "希望院校提供哪些具体技术能力？",
            "缺少能力就无法按模块检索论文。",
            "blocking",
        )

    target_metrics = profile.get("target_metrics", [])
    if not target_metrics:
        add(
            "target_metrics",
            "请给出最重要的 1–3 项量化验收指标、单位和目标范围。",
            "没有数值指标时不能判断方案是否达到企业目标。",
            "blocking",
        )
    else:
        for metric in target_metrics:
            if not metric.get("test_condition"):
                add(
                    f"target_metrics.{metric['metric_id']}.test_condition",
                    f"“{metric['raw_text']}”应在什么测试条件和方法下验收？",
                    "同一指标在不同测试条件下不能直接比较。",
                    "blocking",
                )
    if not profile.get("constraints"):
        add(
            "constraints",
            "成本、周期、尺寸、设备、材料或法规方面有哪些硬约束？",
            "缺少边界时只能形成实验室建议，不能形成落地承诺。",
            "important",
        )
    if not profile.get("existing_foundations"):
        add(
            "existing_foundations",
            "企业已有样机、工艺、设备、数据和工程团队基础分别是什么？",
            "用于确定项目从哪个验证阶段开始。",
            "important",
        )
    if not profile.get("excluded_approaches"):
        add(
            "excluded_approaches",
            "是否存在明确不能采用的材料、工艺或技术路线？",
            "避免候选方案越过企业边界。",
            "informational",
        )
    for fragment in profile.get("unparsed_fragments", []):
        add(
            "unparsed_fragments",
            f"请确认这段原话应归入哪个需求字段：“{fragment}”",
            "规则解析器没有可靠理解该片段。",
            "important",
        )

    blocking_count = sum(item["severity"] == "blocking" for item in questions)
    return {
        "status": "needs_clarification" if blocking_count else "ready_for_confirmation",
        "blocking_count": blocking_count,
        "questions": questions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _related_problem(capability: str, problems: Sequence[str]) -> str | None:
    for capability_hint, problem_hints in CAPABILITY_PROBLEM_HINTS.items():
        if capability_hint in capability:
            for problem in problems:
                if any(hint in problem for hint in problem_hints):
                    return problem
    return None


def _metrics_for_capability(
    capability: str, metrics: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for metric in metrics:
        hints = METRIC_CAPABILITY_HINTS.get(str(metric.get("name")), ())
        if any(hint in capability for hint in hints):
            selected.append(dict(metric))
    return selected


def decompose_technical_need(
    profile: dict[str, Any], *, confirmed: bool = False
) -> list[dict[str, Any]]:
    """Turn only explicit enterprise values into independently retrievable modules."""
    capabilities = _unique_strings(profile.get("required_capabilities", []))
    problems = _unique_strings(profile.get("technical_problems", []))
    module_seeds = capabilities or problems
    modules: list[dict[str, Any]] = []
    for index, seed in enumerate(module_seeds, start=1):
        is_capability = seed in capabilities
        source_field = "required_capabilities" if is_capability else "technical_problems"
        related_problem = _related_problem(seed, problems) if is_capability else seed
        metrics = _metrics_for_capability(seed, profile.get("target_metrics", []))
        source_phrases = _phrases_for(profile, source_field, seed)
        missing: list[str] = []
        if not metrics:
            missing.append("缺少与本模块直接对应的量化验收指标")
        elif any(not metric.get("test_condition") for metric in metrics):
            missing.append("部分指标缺少测试条件或方法")
        if not related_problem:
            missing.append("企业未明确说明该能力对应的当前问题")
        modules.append(
            {
                "module_id": f"M{index:02d}",
                "name": seed,
                "business_goal": profile.get("product", "未明确"),
                "problem_statement": related_problem or "待企业确认",
                "required_capability": seed if is_capability else "待企业确认",
                "source_field": source_field,
                "source_phrases": source_phrases,
                "source_type": "enterprise_confirmed",
                "acceptance_metrics": metrics,
                "global_constraints": list(profile.get("constraints", [])),
                "inputs": [],
                "outputs": [],
                "interfaces": [],
                "dependencies": [],
                "missing_information": missing,
                "confirmation_status": (
                    "confirmed_by_user" if confirmed else "pending_user_confirmation"
                ),
            }
        )
    return modules


def build_module_query(module: dict[str, Any], profile: dict[str, Any]) -> str:
    """Build a module-specific retrieval query from confirmed values only."""
    parts = [
        f"技术模块：{module['name']}",
        f"所需能力：{module['required_capability']}",
        f"当前问题：{module['problem_statement']}",
        f"产品：{profile.get('product', '未明确')}",
        f"行业场景：{profile.get('industry', '未明确')}",
    ]
    metrics = module.get("acceptance_metrics", [])
    if metrics:
        parts.append("验收指标：" + "；".join(metric["raw_text"] for metric in metrics))
    if module.get("source_phrases"):
        parts.append("企业原话：" + "；".join(module["source_phrases"]))
    return "\n".join(parts)


def _evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": item["chunk_id"],
        "title": item["title"],
        "author": item.get("author", ""),
        "teacher": item.get("teacher", ""),
        "page_start": item["page_start"],
        "page_end": item["page_end"],
        "similarity": round(float(item["similarity"]), 4),
        "excerpt": str(item.get("excerpt", "")),
        "source_type": "paper_evidence",
    }


def _compose_solution_options(
    profile: dict[str, Any],
    modules: Sequence[dict[str, Any]],
    match_result: dict[str, Any],
    module_evidence: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    confirmed: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recommendations = match_result.get("recommendations", [])
    if not confirmed:
        return (
            {
                "status": "blocked",
                "allowed_solution_count": 0,
                "reasons": ["企业尚未确认需求拆解。"],
            },
            [],
        )
    if not modules or not recommendations:
        return (
            {
                "status": "blocked",
                "allowed_solution_count": 0,
                "reasons": ["缺少技术模块或教师匹配结果。"],
            },
            [],
        )

    recommendation = recommendations[0]
    teacher = recommendation["recommended_teacher"]
    module_support: list[dict[str, Any]] = []
    supported_count = 0
    for module in modules:
        evidence = [
            _evidence_ref(item)
            for item in module_evidence.get(module["module_id"], {}).get(teacher, [])[:3]
        ]
        status = "supported" if evidence else "evidence_gap"
        supported_count += bool(evidence)
        module_support.append(
            {
                "module_id": module["module_id"],
                "module_name": module["name"],
                "status": status,
                "teacher": teacher,
                "paper_evidence": evidence,
                "acceptance_metrics": list(module.get("acceptance_metrics", [])),
                "missing_information": list(module.get("missing_information", [])),
            }
        )

    if supported_count == 0:
        return (
            {
                "status": "blocked",
                "allowed_solution_count": 0,
                "reasons": ["所有技术模块都缺少达到阈值的论文 Chunk 证据。"],
            },
            [],
        )

    missing_metrics = not profile.get("target_metrics")
    unsupported = [
        item["module_name"]
        for item in module_support
        if item["status"] != "supported"
    ]
    reasons = [
        "当前证据只足以形成一个证据优先方案，暂不制造三个看似不同的方案。"
    ]
    if missing_metrics:
        reasons.append("企业尚未提供明确量化指标，方案只能作为待确认草案。")
    if unsupported:
        reasons.append("以下模块仍缺证据：" + "、".join(unsupported))
    status = "passed" if not missing_metrics and not unsupported else "provisional"
    option = {
        "solution_id": "S01",
        "name": f"{profile.get('product', '企业项目')}—证据优先联合验证方案",
        "strategy": "evidence_first",
        "status": "ready_for_feasibility" if status == "passed" else "provisional",
        "overall_principle": (
            "优先复现已有论文证据，再逐模块验证企业工况，最后决定是否集成放大。"
        ),
        "principle_source_type": "system_suggestion",
        "recommended_teacher": teacher,
        "legacy_matching_score": recommendation.get("matching_score"),
        "modules": module_support,
        "expected_value": "验证已检索科研能力能否满足企业确认的技术模块。",
        "expected_value_source_type": "system_suggestion",
        "assumptions": [
            "论文结果需要在企业样品、设备和测试条件下重新验证。",
            "知识产权、法规、安全、成本和供应链结论仍需专业复核。",
        ],
        "uncovered_gaps": unsupported,
        "differentiator": "仅采用当前可定位论文证据，不虚构第二或第三条技术路线。",
    }
    return (
        {
            "status": status,
            "allowed_solution_count": 1,
            "reasons": reasons,
        },
        [option],
    )


def _acceptance_items(module: dict[str, Any]) -> list[dict[str, str]]:
    metrics = module.get("acceptance_metrics", [])
    if metrics:
        return [
            {
                "criterion": metric["raw_text"],
                "test_condition": metric.get("test_condition") or "待企业确认",
                "source_type": "enterprise_confirmed",
            }
            for metric in metrics
        ]
    return [
        {
            "criterion": "待企业补充本模块量化验收指标",
            "test_condition": "待企业确认",
            "source_type": "unknown",
        }
    ]


def _build_route(solution: dict[str, Any] | None) -> dict[str, Any]:
    if not solution:
        return {"status": "blocked", "nodes": [], "edges": []}

    nodes: list[dict[str, Any]] = [
        {
            "node_id": "R01",
            "name": "冻结需求规格与测试口径",
            "stage": "需求确认",
            "inputs": ["企业需求原话", "澄清问题与确认记录"],
            "actions": ["逐项确认技术模块、指标、测试条件和排除路线"],
            "outputs": ["双方确认的需求规格"],
            "acceptance_criteria": [
                {
                    "criterion": "所有阻塞型澄清问题已回答",
                    "test_condition": "双方书面确认",
                    "source_type": "system_suggestion",
                }
            ],
            "predecessors": [],
            "responsible_party": "企业与院校共同确认",
            "responsible_party_source_type": "system_suggestion",
            "risks": ["指标定义或测试口径不一致"],
            "alternatives": ["暂停方案设计并补充需求"],
            "evidence": [],
            "status": "planned",
        }
    ]
    edges: list[dict[str, str]] = []
    previous_ids = ["R01"]
    for index, module in enumerate(solution["modules"], start=2):
        node_id = f"R{index:02d}"
        supported = module["status"] == "supported"
        nodes.append(
            {
                "node_id": node_id,
                "name": f"验证模块：{module['module_name']}",
                "stage": "模块可行性验证",
                "inputs": ["双方确认的需求规格", "论文证据与实验条件"],
                "actions": ["复现实验基线", "在企业工况下进行对照测试"],
                "outputs": [f"{module['module_name']}验证记录与样品/数据"],
                "acceptance_criteria": _acceptance_items(module),
                "predecessors": ["R01"],
                "responsible_party": "院校负责实验，企业负责工况与验收确认",
                "responsible_party_source_type": "system_suggestion",
                "risks": (
                    ["论文条件与企业工况不一致"]
                    if supported
                    else ["当前没有达到阈值的论文证据"]
                ),
                "alternatives": ["缩小范围开展预研或补充外部证据"],
                "evidence": list(module["paper_evidence"]),
                "status": "planned" if supported else "blocked",
            }
        )
        edges.append({"from": "R01", "to": node_id, "relation": "precedes"})
        previous_ids.append(node_id)

    next_number = len(nodes) + 1
    if len(solution["modules"]) > 1:
        integration_id = f"R{next_number:02d}"
        module_node_ids = [
            node["node_id"]
            for node in nodes
            if node["stage"] == "模块可行性验证"
        ]
        nodes.append(
            {
                "node_id": integration_id,
                "name": "模块集成与样机验证",
                "stage": "集成验证",
                "inputs": ["各模块验证记录", "企业接口与工况"],
                "actions": ["完成接口联调与系统级测试"],
                "outputs": ["集成样机与系统测试记录"],
                "acceptance_criteria": [
                    {
                        "criterion": "达到已确认的系统级验收指标",
                        "test_condition": "按冻结后的企业测试口径",
                        "source_type": "system_suggestion",
                    }
                ],
                "predecessors": module_node_ids,
                "responsible_party": "企业与院校联合",
                "responsible_party_source_type": "system_suggestion",
                "risks": ["单模块性能在集成后下降"],
                "alternatives": ["回退到模块级复核或调整接口"],
                "evidence": [],
                "status": "planned",
            }
        )
        for predecessor in module_node_ids:
            edges.append(
                {"from": predecessor, "to": integration_id, "relation": "precedes"}
            )
        previous_ids = [integration_id]
        next_number += 1

    validation_id = f"R{next_number:02d}"
    nodes.append(
        {
            "node_id": validation_id,
            "name": "企业现场验证与转移决策",
            "stage": "现场验证",
            "inputs": ["样品或样机", "安全、法规、知识产权与成本复核"],
            "actions": ["在真实工况下验收", "执行继续/暂停决策门"],
            "outputs": ["现场验证报告", "技术转移决策记录"],
            "acceptance_criteria": [
                {
                    "criterion": "关键指标通过且重大合规/资源缺口已关闭",
                    "test_condition": "企业确认的现场测试方案",
                    "source_type": "system_suggestion",
                }
            ],
            "predecessors": previous_ids,
            "responsible_party": "企业主责，院校提供技术支持",
            "responsible_party_source_type": "system_suggestion",
            "risks": ["实验室结果不能迁移到现场", "知识产权或法规风险未关闭"],
            "alternatives": ["暂停转移并返回模块验证"],
            "evidence": [],
            "status": "planned",
        }
    )
    for predecessor in previous_ids:
        edges.append(
            {"from": predecessor, "to": validation_id, "relation": "precedes"}
        )
    return {"status": "planned", "nodes": nodes, "edges": edges}


def _score_band(score: int | None) -> str:
    if score is None:
        return "未知"
    if score < 40:
        return "低"
    if score < 60:
        return "中低"
    if score < 80:
        return "中"
    return "较高"


def _evaluate_transfer(
    profile: dict[str, Any],
    modules: Sequence[dict[str, Any]],
    solution: dict[str, Any] | None,
    clarification: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    supported = [
        module
        for module in (solution or {}).get("modules", [])
        if module["status"] == "supported"
    ]
    metrics = profile.get("target_metrics", [])
    metrics_complete = bool(metrics) and all(
        metric.get("test_condition") for metric in metrics
    )
    all_modules_supported = bool(modules) and len(supported) == len(modules)
    hard_gates = [
        {
            "gate_id": "G01",
            "name": "需求拆解已由用户确认",
            "status": "passed" if confirmed else "failed",
            "blocking_stage": "solution_generation",
            "evidence": ["当前会话确认记录"] if confirmed else [],
        },
        {
            "gate_id": "G02",
            "name": "关键指标及测试条件完整",
            "status": "passed" if metrics_complete else "failed",
            "blocking_stage": "feasibility_acceptance",
            "evidence": [metric["raw_text"] for metric in metrics],
        },
        {
            "gate_id": "G03",
            "name": "所有核心模块具有论文 Chunk 证据",
            "status": "passed" if all_modules_supported else "failed",
            "blocking_stage": "solution_generation",
            "evidence": [item["module_name"] for item in supported],
        },
        {
            "gate_id": "G04",
            "name": "知识产权、法规与安全已经专业复核",
            "status": "pending",
            "blocking_stage": "commercial_transfer",
            "evidence": [],
        },
        {
            "gate_id": "G05",
            "name": "关键设备、材料、人员和预算可获得",
            "status": "pending",
            "blocking_stage": "project_launch",
            "evidence": list(profile.get("existing_foundations", [])),
        },
    ]

    demand_score = round(len(supported) / len(modules) * 100) if modules else None
    best_similarities = [
        max(item["similarity"] for item in module["paper_evidence"])
        for module in supported
        if module["paper_evidence"]
    ]
    evidence_score = (
        round(sum(best_similarities) / len(best_similarities) * 100)
        if best_similarities
        else None
    )
    dimensions = {
        "demand_fit": {
            "label": "技术模块证据覆盖",
            "score": demand_score,
            "weight": TRANSFER_WEIGHTS["demand_fit"],
            "source_type": (
                "paper_evidence" if demand_score is not None else "unknown"
            ),
            "missing": [] if all_modules_supported else ["部分模块缺少论文证据"],
        },
        "evidence_strength": {
            "label": "检索证据强度",
            "score": evidence_score,
            "weight": TRANSFER_WEIGHTS["evidence_strength"],
            "source_type": (
                "paper_evidence" if evidence_score is not None else "unknown"
            ),
            "missing": (
                [] if evidence_score is not None else ["没有达到阈值的论文 Chunk"]
            ),
        },
        "engineering_maturity": {
            "label": "工程成熟度",
            "score": None,
            "weight": TRANSFER_WEIGHTS["engineering_maturity"],
            "source_type": "unknown",
            "missing": ["尚未完成样机、工艺窗口、良率和现场验证调查"],
        },
        "landing_constraints": {
            "label": "落地约束成熟度",
            "score": None,
            "weight": TRANSFER_WEIGHTS["landing_constraints"],
            "source_type": "unknown",
            "missing": ["成本、知识产权、法规、安全和资源可得性尚未完整复核"],
        },
    }
    known = [item for item in dimensions.values() if item["score"] is not None]
    known_weight = sum(float(item["weight"]) for item in known)
    raw_known_score = (
        sum(float(item["score"]) * float(item["weight"]) for item in known)
        / known_weight
        if known_weight
        else None
    )
    known_score = (
        int(round(raw_known_score / 5) * 5) if raw_known_score is not None else None
    )
    metric_component = (
        sum(bool(metric.get("test_condition")) for metric in metrics) / len(metrics)
        if metrics
        else 0.0
    )
    completeness = round(
        100
        * (
            (len(supported) / len(modules) if modules else 0.0) * 0.6
            + metric_component * 0.4
        )
    )

    if not confirmed:
        decision = "pause_for_confirmation"
    elif not solution or not all_modules_supported:
        decision = "pause_for_evidence"
    elif not metrics_complete or clarification.get("blocking_count", 0):
        decision = "proceed_to_clarification"
    else:
        decision = "proceed_to_feasibility"
    return {
        "method": "four_dimension_known_only_v1",
        "decision": decision,
        "hard_gates": hard_gates,
        "dimensions": dimensions,
        "known_dimension_score": known_score,
        "known_dimension_band": _score_band(known_score),
        "known_weight": round(known_weight, 2),
        "unknown_dimensions": [
            key for key, value in dimensions.items() if value["score"] is None
        ],
        "evidence_completeness": completeness,
        "note": "未知维度不进入分母；该分数不是产业化成功率。",
    }


def _build_landing_plan(
    route: dict[str, Any], transfer: dict[str, Any]
) -> list[dict[str, Any]]:
    milestones: list[dict[str, Any]] = []
    for index, node in enumerate(route.get("nodes", []), start=1):
        criteria = [item["criterion"] for item in node["acceptance_criteria"]]
        milestones.append(
            {
                "milestone_id": f"L{index:02d}",
                "route_node_id": node["node_id"],
                "goal": node["name"],
                "responsible_party": node["responsible_party"],
                "inputs": list(node["inputs"]),
                "deliverables": list(node["outputs"]),
                "acceptance_or_exit_criteria": criteria,
                "dependencies": list(node["predecessors"]),
                "budget_or_resources": "待双方根据任务范围确认",
                "budget_source_type": "unknown",
                "risks": list(node["risks"]),
                "mitigations": list(node["alternatives"]),
                "decision_gate": (
                    "满足验收标准并关闭阻塞风险后进入下一阶段，否则暂停或回退。"
                ),
                "source_type": "system_suggestion",
            }
        )
    if transfer["decision"] != "proceed_to_feasibility" and milestones:
        milestones[0]["decision_gate"] = (
            "当前转化决策为 "
            f"{transfer['decision']}；先关闭失败的硬门槛，再进入后续阶段。"
        )
    return milestones


def build_enterprise_solution(
    profile: dict[str, Any],
    match_result: dict[str, Any],
    module_evidence: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    clarification = build_clarification(profile)
    modules = decompose_technical_need(profile, confirmed=confirmed)
    solution_gate, options = _compose_solution_options(
        profile,
        modules,
        match_result,
        module_evidence,
        confirmed=confirmed,
    )
    selected = options[0] if options else None
    route = _build_route(selected)
    transfer = _evaluate_transfer(
        profile,
        modules,
        selected,
        clarification,
        confirmed=confirmed,
    )
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "requirement_confirmation": {
            "confirmed": confirmed,
            "status": (
                "confirmed_by_user" if confirmed else "pending_user_confirmation"
            ),
        },
        "clarification": clarification,
        "need_modules": modules,
        "solution_gate": solution_gate,
        "solution_options": options,
        "selected_solution_id": selected["solution_id"] if selected else None,
        "technical_route": route,
        "transfer_evaluation": transfer,
        "landing_plan": _build_landing_plan(route, transfer),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    validate_solution_bundle(bundle, profile)
    return bundle


def _assert_acyclic(route: dict[str, Any]) -> None:
    node_ids = {node["node_id"] for node in route.get("nodes", [])}
    graph = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in route.get("edges", []):
        source, target = edge.get("from"), edge.get("to")
        if source not in node_ids or target not in node_ids:
            raise RuntimeError("技术路线引用了不存在的节点")
        graph[source].append(target)
        indegree[target] += 1
    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for target in graph[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        raise RuntimeError("技术路线存在循环依赖")


def validate_solution_bundle(
    bundle: dict[str, Any], enterprise_profile: dict[str, Any] | str
) -> None:
    """Reject untraceable modules, malformed evidence, and score denominator errors."""
    if isinstance(enterprise_profile, dict):
        request_evidence_text = enterprise_profile.get(
            "confirmed_request",
            enterprise_profile.get("original_request", ""),
        )
    else:
        request_evidence_text = enterprise_profile
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("企业方案 schema_version 不受支持")
    modules = bundle.get("need_modules")
    if not isinstance(modules, list):
        raise RuntimeError("企业方案 need_modules 必须是数组")
    module_ids = [module.get("module_id") for module in modules]
    if len(module_ids) != len(set(module_ids)):
        raise RuntimeError("技术模块 ID 重复")
    for module in modules:
        if module.get("source_type") != "enterprise_confirmed":
            raise RuntimeError("技术模块必须来自企业确认字段")
        if not module.get("source_phrases"):
            raise RuntimeError(f"技术模块缺少企业原文：{module.get('module_id')}")
        if any(
            phrase.casefold() not in request_evidence_text.casefold()
            for phrase in module["source_phrases"]
        ):
            raise RuntimeError("技术模块引用了不存在的企业原文")

    valid_modules = set(module_ids)
    for option in bundle.get("solution_options", []):
        if option.get("principle_source_type") != "system_suggestion":
            raise RuntimeError("方案原则必须明确标记为系统建议")
        for module in option.get("modules", []):
            if module.get("module_id") not in valid_modules:
                raise RuntimeError("候选方案引用了未知技术模块")
            evidence = module.get("paper_evidence", [])
            if module.get("status") == "supported" and not evidence:
                raise RuntimeError("受支持模块缺少论文证据")
            for item in evidence:
                required = {
                    "chunk_id",
                    "title",
                    "teacher",
                    "page_start",
                    "page_end",
                    "similarity",
                    "source_type",
                }
                if (
                    not required.issubset(item)
                    or item["source_type"] != "paper_evidence"
                ):
                    raise RuntimeError("模块论文证据字段不完整")

    _assert_acyclic(bundle.get("technical_route", {}))
    evaluation = bundle.get("transfer_evaluation", {})
    dimensions = evaluation.get("dimensions", {})
    if set(dimensions) != set(TRANSFER_WEIGHTS):
        raise RuntimeError("转化评估维度不完整")
    known = [
        value for value in dimensions.values() if value.get("score") is not None
    ]
    expected_weight = round(sum(float(value["weight"]) for value in known), 2)
    if expected_weight != evaluation.get("known_weight"):
        raise RuntimeError("未知维度未正确移出评分分母")
    for value in dimensions.values():
        if value.get("source_type") not in SOURCE_TYPES:
            raise RuntimeError("转化评估包含未知来源类型")
