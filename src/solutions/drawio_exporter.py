"""Export a structured technical route as native, editable draw.io XML."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any
from xml.etree import ElementTree as ET


NODE_STYLES = {
    "planned": (
        "rounded=1;whiteSpace=wrap;html=1;"
        "fillColor=#dae8fc;strokeColor=#6c8ebf;"
    ),
    "blocked": (
        "rounded=1;whiteSpace=wrap;html=1;"
        "fillColor=#f8cecc;strokeColor=#b85450;"
    ),
}


def _node_label(node: dict[str, Any]) -> str:
    criteria = "；".join(
        str(item.get("criterion", ""))
        for item in node.get("acceptance_criteria", [])
    )
    return (
        f"<b>{escape(str(node['node_id']))} · "
        f"{escape(str(node['name']))}</b>"
        f"<br>{escape(str(node.get('stage', '')))}"
        f"<br>验收：{escape(criteria or '待确认')}"
    )


def route_to_drawio(
    route: dict[str, Any], *, title: str = "企业方案技术路线"
) -> str:
    """Return uncompressed mxGraph XML that opens directly in draw.io."""
    nodes = route.get("nodes", [])
    edges = route.get("edges", [])
    node_ids = {str(node.get("node_id")) for node in nodes}
    if any(
        str(edge.get("from")) not in node_ids
        or str(edge.get("to")) not in node_ids
        for edge in edges
    ):
        raise ValueError("技术路线边引用了不存在的节点")

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": datetime.now(timezone.utc).isoformat(),
            "agent": "industry-academia-agent",
            "version": "enterprise_solution_v1",
        },
    )
    diagram = ET.SubElement(
        mxfile,
        "diagram",
        {"id": "enterprise-route", "name": title},
    )
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1200",
            "dy": "800",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1169",
            "pageHeight": "827",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    for index, node in enumerate(nodes):
        status = str(node.get("status", "planned"))
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": str(node["node_id"]),
                "value": _node_label(node),
                "style": NODE_STYLES.get(status, NODE_STYLES["planned"]),
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": "80" if index % 2 == 0 else "590",
                "y": str(40 + (index // 2) * 170),
                "width": "430",
                "height": "110",
                "as": "geometry",
            },
        )

    for index, edge in enumerate(edges, start=1):
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"E{index:03d}",
                "value": "",
                "style": (
                    "edgeStyle=orthogonalEdgeStyle;rounded=1;"
                    "html=1;endArrow=block;"
                ),
                "edge": "1",
                "parent": "1",
                "source": str(edge["from"]),
                "target": str(edge["to"]),
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {"relative": "1", "as": "geometry"},
        )

    return ET.tostring(mxfile, encoding="unicode", xml_declaration=True)
