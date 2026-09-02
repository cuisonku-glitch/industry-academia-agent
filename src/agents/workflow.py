"""Command-line entry point for the auditable Agent workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .coordinator import (
        DEFAULT_JSON_PATH,
        DEFAULT_DRAWIO_PATH,
        DEFAULT_REPORT_PATH,
        Coordinator,
        build_coordinator,
        save_run,
    )
    from .decision_agents import EvidenceAgent, MatchingAgent, SolutionAgent
    from .report_agent import ReportAgent
    from .source_agents import (
        ClarificationAgent,
        PaperAgent,
        RequirementAgent,
        ResearchAgent,
    )
    from .state import new_state
    from ..extraction.enterprise_parser import DEFAULT_REQUEST
    from ..matching.matcher import DEFAULT_TEACHER_DIRECTORY, DEFAULT_TOP_K
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.agents.coordinator import (
        DEFAULT_JSON_PATH,
        DEFAULT_DRAWIO_PATH,
        DEFAULT_REPORT_PATH,
        Coordinator,
        build_coordinator,
        save_run,
    )
    from src.agents.decision_agents import EvidenceAgent, MatchingAgent, SolutionAgent
    from src.agents.report_agent import ReportAgent
    from src.agents.source_agents import (
        ClarificationAgent,
        PaperAgent,
        RequirementAgent,
        ResearchAgent,
    )
    from src.agents.state import new_state
    from src.extraction.enterprise_parser import DEFAULT_REQUEST
    from src.matching.matcher import DEFAULT_TEACHER_DIRECTORY, DEFAULT_TOP_K


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行可追踪的产学研 Agent 工作流")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="真实企业需求原话")
    source.add_argument("--input-file", type=Path, help="UTF-8 企业需求文本文件")
    source.add_argument(
        "--demo",
        action="store_true",
        help="显式使用操作指南中的 X 射线探伤示例",
    )
    parser.add_argument("--teachers", type=Path, default=DEFAULT_TEACHER_DIRECTORY)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--output-drawio", type=Path, default=DEFAULT_DRAWIO_PATH)
    parser.add_argument(
        "--confirm-requirement",
        action="store_true",
        help="确认已核对需求拆解；未设置时方案生成闸门保持暂停",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.demo:
        request_text = DEFAULT_REQUEST
        input_mode = "demo"
    elif args.input_file:
        request_text = args.input_file.read_text(encoding="utf-8")
        input_mode = "user_file"
    else:
        request_text = args.text
        input_mode = "user"

    coordinator = build_coordinator(args.teachers, top_k=args.top_k)
    paper_agent = coordinator.agents[3]
    print(f"本地 Embedding 设备：{paper_agent.matcher.embedder.device}")
    print(f"输入类型：{'指南示例演示' if input_mode == 'demo' else '真实企业需求'}")
    state = coordinator.run(
        request_text,
        input_mode=input_mode,
        requirement_confirmed=args.confirm_requirement,
    )
    json_path, report_path, drawio_path = save_run(
        state,
        args.output_json,
        args.output_report,
        args.output_drawio,
    )
    print("Agent 执行顺序：")
    for item in state["trace"]:
        print(f"- {item['sequence']}. {item['agent']}：{item['status']}")
    first = state["match_result"]["recommendations"][0]
    print(
        f"推荐结果：{first['recommended_teacher']}｜"
        f"{first['matching_score']:.2f}/100｜"
        f"证据审查 {state['evidence_review']['overall_status']}"
    )
    print(f"结构化运行记录：{json_path}")
    print(f"匹配报告：{report_path}")
    print(f"可编辑技术路线：{drawio_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
