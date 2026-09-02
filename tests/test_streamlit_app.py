"""Streamlit UI tests that do not load the GPU model or call Moonshot."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from src.extraction.enterprise_parser import parse_enterprise_need
from src.solutions import build_enterprise_solution, route_to_drawio


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "app.py"


def make_display_state() -> dict[str, Any]:
    request = (
        "我们开发工业X射线探伤设备，现有灵敏度不足，希望高灵敏度，"
        "灵敏度至少1200 μC Gy^-1 cm^-2，在50 kVp条件下测试，"
        "已有小型样机，不能使用铅。"
    )
    profile = parse_enterprise_need(request)
    match_result = {
            "recommendations": [
                {
                    "recommended_teacher": "徐修文",
                    "matching_score": 59.19,
                    "paper_evidence": [
                        {
                            "title": "测试论文",
                            "page_start": 8,
                            "page_end": 9,
                            "chunk_id": "paper_chunk_001",
                            "similarity": 0.8,
                            "excerpt": "论文证据摘录。",
                            "teacher": "徐修文",
                            "author": "测试学生",
                        }
                    ],
                    "core_matching_technologies": [
                        {
                            "required_capability": "高灵敏度X射线探测",
                            "matched_teacher_capability": "低压X射线探测器",
                            "similarity": 0.7,
                        }
                    ],
                    "relevant_papers": [
                        {
                            "title": "测试论文",
                            "author": "测试学生",
                            "year": 2025,
                            "evidence_pages": [8, 9],
                            "best_similarity": 0.8,
                        }
                    ],
                    "matching_reason": ["存在可定位的论文证据。"],
                    "technology_gap": [
                        {"required_capability": "低成本材料", "similarity": 0.4}
                    ],
                    "potential_collaboration_directions": ["开展样品验证。"],
                    "score_breakdown": {
                        "semantic_similarity": {
                            "raw": 0.5,
                            "weight": 0.45,
                            "contribution": 22.5,
                        }
                    },
                }
            ]
        }
    module_evidence = {
        "M01": {"徐修文": list(match_result["recommendations"][0]["paper_evidence"])}
    }
    bundle = build_enterprise_solution(
        profile,
        match_result,
        module_evidence,
        confirmed=True,
    )
    return {
        "request_text": request,
        "match_result": match_result,
        "evidence_review": {"overall_status": "passed"},
        "solution_bundle": bundle,
        "route_drawio": route_to_drawio(bundle["technical_route"]),
        "report": "# 测试报告\n",
    }


class StreamlitAppTests(unittest.TestCase):
    def _app(self) -> AppTest:
        app = AppTest.from_file(str(APP_PATH), default_timeout=20)
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_page_has_both_required_workflows(self) -> None:
        app = self._app()
        self.assertEqual(
            [tab.label for tab in app.tabs],
            ["企业端 · 组合方案", "论文问答"],
        )
        self.assertEqual(app.text_area[0].label, "企业需求原话")
        self.assertEqual(app.text_input[0].label, "问")
        self.assertEqual([button.label for button in app.button], ["解析需求", "查询论文"])

    def test_empty_enterprise_request_is_rejected_before_model_loading(self) -> None:
        app = self._app()
        app.button[0].click().run()
        self.assertIn("请先输入企业需求原话", app.error[0].value)
        self.assertEqual(len(app.exception), 0)

    def test_requirement_is_previewed_before_gpu_workflow(self) -> None:
        app = self._app()
        app.text_area[0].input(
            "我们开发工业X射线探伤设备，需要高灵敏度探测，已有小型样机。"
        )
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "核对结构化拆解",
            "\n".join(item.value for item in app.markdown),
        )
        self.assertIn("确认需求并生成组合方案", [item.label for item in app.button])

    def test_paper_question_requires_explicit_data_consent(self) -> None:
        app = self._app()
        app.text_input[0].input("这个老师主要做什么？")
        app.button[1].click().run()
        self.assertIn("请先确认论文片段发送范围", app.error[0].value)
        self.assertEqual(len(app.exception), 0)

    def test_existing_match_state_renders_all_required_result_sections(self) -> None:
        app = self._app()
        app.session_state["match_state"] = make_display_state()
        app.run()
        rendered_text = "\n".join(
            item.value
            for collection in (app.markdown, app.info, app.success, app.warning)
            for item in collection
            if isinstance(item.value, str)
        )
        self.assertIn("核心技术", rendered_text)
        self.assertIn("相关论文", rendered_text)
        self.assertIn("匹配依据", rendered_text)
        self.assertIn("潜在合作建议", rendered_text)
        self.assertIn("转化评估与决策门", rendered_text)
        self.assertIn("分阶段落地计划", rendered_text)
        metric_values = [item.value for item in app.metric]
        self.assertIn("徐修文", metric_values)
        self.assertIn("59.19%", metric_values)


if __name__ == "__main__":
    unittest.main()
