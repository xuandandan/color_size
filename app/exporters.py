from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def _flatten(prefix: str, value: Any, rows: List[Tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten(next_prefix, sub, rows)
        return
    if isinstance(value, list):
        for idx, sub in enumerate(value):
            next_prefix = f"{prefix}[{idx}]"
            _flatten(next_prefix, sub, rows)
        return
    rows.append((prefix or "value", str(value)))


def build_excel_bytes(report_name: str, result_type: str, payload: Dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Result"
    ws.append(["Report Name", report_name])
    ws.append(["Result Type", result_type])
    ws.append([])
    ws.append(["Field", "Value"])

    rows: List[Tuple[str, str]] = []
    _flatten("", payload, rows)
    if not rows:
        rows = [("payload", "{}")]
    for field, value in rows:
        ws.append([field, value])

    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def build_pdf_bytes(report_name: str, result_type: str, payload: Dict[str, Any]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf.setFont("STSong-Light", 12)

    width, height = A4
    y = height - 40
    lines = [
        f"Report Name: {report_name}",
        f"Result Type: {result_type}",
        "",
        "Payload:",
    ]
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    lines.extend(payload_text.splitlines())

    for line in lines:
        if y < 40:
            pdf.showPage()
            pdf.setFont("STSong-Light", 12)
            y = height - 40
        pdf.drawString(40, y, line[:120])
        y -= 16

    pdf.save()
    return output.getvalue()
