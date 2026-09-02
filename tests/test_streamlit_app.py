"""Streamlit UI tests that do not load the GPU model or call Moonshot."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from src.extraction.enterprise_parser import parse_enterprise_need
from src.repository import PaperCatalog
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
    def setUp(self) -> None:
        self.version_directory = tempfile.TemporaryDirectory()
        self.academy_directory = tempfile.TemporaryDirectory()
        os.environ["INDUSTRY_AGENT_VERSION_DIR"] = self.version_directory.name
        os.environ["INDUSTRY_AGENT_CATALOG_PATH"] = str(
            Path(self.academy_directory.name) / "papers.sqlite3"
        )
        os.environ["INDUSTRY_AGENT_PAPER_LIBRARY_DIR"] = self.academy_directory.name

    def tearDown(self) -> None:
        os.environ.pop("INDUSTRY_AGENT_VERSION_DIR", None)
        os.environ.pop("INDUSTRY_AGENT_CATALOG_PATH", None)
        os.environ.pop("INDUSTRY_AGENT_PAPER_LIBRARY_DIR", None)
        self.version_directory.cleanup()
        self.academy_directory.cleanup()

    def _app(self) -> AppTest:
        app = AppTest.from_file(str(APP_PATH), default_timeout=20)
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    @staticmethod
    def _button(app: AppTest, label: str):
        return next(button for button in app.button if button.label == label)

    def test_page_has_both_required_workflows(self) -> None:
        app = self._app()
        self.assertEqual(
            [tab.label for tab in app.tabs],
            ["企业端 · 组合方案", "论文问答"],
        )
        self.assertEqual(app.text_area[0].label, "企业需求原话")
        self.assertEqual(app.text_input[0].label, "问")
        button_labels = [button.label for button in app.button]
        self.assertIn("载入江西电缆公开验收案例", button_labels)
        self.assertIn("解析需求", button_labels)
        self.assertIn("查询论文", button_labels)

    def test_academy_workbench_opens_without_loading_models(self) -> None:
        paper = Path(self.academy_directory.name) / "paper.pdf"
        paper.write_bytes(b"%PDF-1.4 academy catalog fixture")
        PaperCatalog(Path(os.environ["INDUSTRY_AGENT_CATALOG_PATH"])).register_pdf(
            paper,
            title="可检索院校论文",
            teacher="导师甲",
            ingestion_status="metadata_pending",
        )
        app = self._app()
        app.segmented_control[0].select("院校端 · 成果对接").run()

        self.assertEqual(len(app.exception), 0)
        self.assertIn("院校端 · 论文成果工作台", [item.value for item in app.title])
        self.assertIn(
            "搜索导师、作者、题名或标签",
            [item.label for item in app.text_input],
        )
        self.assertIn("1", [item.value for item in app.metric])

    def test_empty_enterprise_request_is_rejected_before_model_loading(self) -> None:
        app = self._app()
        self._button(app, "解析需求").click().run()
        self.assertIn("请先输入企业需求原话", app.error[0].value)
        self.assertEqual(len(app.exception), 0)

    def test_requirement_is_previewed_before_gpu_workflow(self) -> None:
        app = self._app()
        app.text_area[0].input(
            "我们开发工业X射线探伤设备，需要高灵敏度探测，已有小型样机。"
        )
        self._button(app, "解析需求").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "核对结构化拆解",
            "\n".join(item.value for item in app.markdown),
        )
        button_labels = [item.label for item in app.button]
        self.assertIn("保存当前修改为新版本", button_labels)
        self.assertIn("确认版本并生成组合方案", button_labels)
        confirm_button = self._button(app, "确认版本并生成组合方案")
        self.assertTrue(confirm_button.disabled)

    def test_public_case_can_be_loaded_without_model_loading(self) -> None:
        app = self._app()
        self._button(app, "载入江西电缆公开验收案例").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("江西电缆有限责任公司", app.text_area[0].value)
        self.assertIn(
            "不代表本项目获得了该企业委托",
            "\n".join(item.value for item in app.info),
        )

    def test_parsed_requirement_must_be_saved_before_confirmation(self) -> None:
        app = self._app()
        app.text_area[0].input(
            "我们开发工业X射线探伤设备，需要高灵敏度探测，已有小型样机。"
        )
        self._button(app, "解析需求").click().run()
        self._button(app, "保存当前修改为新版本").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(list(Path(self.version_directory.name).glob("ENV-*.json")))
        self.assertIn("待确认版本", "\n".join(item.value for item in app.success))
        self.assertTrue(self._button(app, "确认版本并生成组合方案").disabled)

    def test_paper_question_requires_explicit_data_consent(self) -> None:
        app = self._app()
        app.text_input[0].input("这个老师主要做什么？")
        self._button(app, "查询论文").click().run()
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
