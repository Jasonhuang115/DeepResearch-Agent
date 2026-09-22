from __future__ import annotations

from typing import Any


def wake_reports(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    reports = raw.get("reports")
    if not isinstance(reports, list):
        return []
    out: list[dict[str, Any]] = []
    for item in reports:
        if not isinstance(item, dict):
            continue
        path = str(item.get("report_path") or "").strip()
        sub_id = str(item.get("id") or "").strip()
        if not path or not sub_id:
            continue
        out.append(
            {
                "id": sub_id,
                "status": str(item.get("status") or ""),
                "report_path": path,
            }
        )
    return out


def wake_reports_block(raw: Any) -> str:
    reports = wake_reports(raw)
    if not reports:
        return ""
    lines = [
        "Subagent reports are ready. Read each path with Glob, Grep, or Read and summarize the conclusions.",
        "Do not paste raw tool logs.",
    ]
    for item in reports:
        lines.append(f"- id={item['id']} status={item['status']} path={item['report_path']}")
    return "\n".join(lines)


def wake_user_cue(language: str) -> str:
    if language == "Chinese":
        return "阅读系统上下文里列出的 subagent 报告路径，用 Glob、Grep 或 Read 读取，并总结结论。不要粘贴工具日志。"
    return (
        "Read the subagent report paths listed in the system context with Glob, Grep, or Read, "
        "and summarize the conclusions. Do not paste raw tool logs."
    )
