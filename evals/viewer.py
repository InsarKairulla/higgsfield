from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from evals.trace import Trace


def _pretty_json(value: Any) -> str:
    return html.escape(json.dumps(value, indent=2, ensure_ascii=False))


def _failed_checks(repeat: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    score = repeat.get("score") or {}
    for metric in score.get("metrics", []):
        if metric.get("passed"):
            continue
        if metric.get("name") == "hard_assertions":
            assertions = metric.get("details", {}).get("assertions", [])
            for assertion in assertions:
                if not assertion.get("passed"):
                    failures.append(f"hard_assertions: {assertion.get('message')}")
        else:
            failures.append(f"{metric.get('name')}: {metric.get('summary')}")
    return failures


def _resolve_trace_path(output_dir: Path, trace_path: str) -> Path:
    candidate = Path(trace_path)
    return candidate if candidate.is_absolute() else output_dir / candidate


def _render_message(index: int, message: dict[str, Any]) -> str:
    role = html.escape(str(message.get("role") or "unknown"))
    label = f"{index + 1}. {role}"
    if message.get("name"):
        label += f" {html.escape(str(message['name']))}"
    if "latency_ms" in message:
        label += f" ({int(message.get('latency_ms', 0))} ms)"

    body_parts: list[str] = []
    if "content" in message:
        content = message.get("content")
        if isinstance(content, str):
            body_parts.append(f"<pre>{html.escape(content)}</pre>")
        else:
            body_parts.append(f"<pre>{_pretty_json(content)}</pre>")
    if message.get("text"):
        body_parts.append(f"<pre>{html.escape(str(message['text']))}</pre>")
    tool_calls = message.get("tool_calls") or []
    for tool_call in tool_calls:
        body_parts.append(
            "<details class='tool-call'>"
            f"<summary>tool call: {html.escape(str(tool_call.get('name') or 'unknown'))}</summary>"
            f"<pre>{_pretty_json(tool_call.get('args') or {})}</pre>"
            "</details>"
        )
    return (
        f"<details class='message role-{role}' open>"
        f"<summary>{label}</summary>"
        + "".join(body_parts)
        + "</details>"
    )


def render_run_viewer(report: dict[str, Any], output_dir: str | Path) -> str:
    output_path = Path(output_dir)
    nav_items: list[str] = []
    sections: list[str] = []

    ordered_cases = sorted(
        report.get("cases", []),
        key=lambda case: (case.get("status") == "pass", case.get("case_id")),
    )

    for case in ordered_cases:
        for repeat in case.get("repeats", []):
            section_id = f"{case['case_id']}-repeat-{repeat['repeat_index']}"
            nav_items.append(
                "<li>"
                f"<a href='#{html.escape(section_id)}'>{html.escape(case['case_id'])} "
                f"(repeat {repeat['repeat_index']}, {html.escape(case['status'])})</a>"
                "</li>"
            )

            trace = Trace.from_path(_resolve_trace_path(output_path, repeat["trace_path"]))
            failures = _failed_checks(repeat)
            failure_html = (
                "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in failures) + "</ul>"
                if failures
                else "<p>No failed checks.</p>"
            )
            messages_html = "".join(
                _render_message(index, message)
                for index, message in enumerate(trace.messages)
            )
            sections.append(
                "<section class='trace-card' "
                f"id='{html.escape(section_id)}'>"
                f"<h2>{html.escape(case['case_id'])} - repeat {repeat['repeat_index']}</h2>"
                f"<p><strong>Status:</strong> {html.escape(case['status'])} | "
                f"<strong>Pass summary:</strong> {html.escape(case['pass_summary'])} | "
                f"<strong>Trace:</strong> {html.escape(repeat['trace_path'])}</p>"
                "<div class='failures'>"
                "<h3>Failed Checks</h3>"
                f"{failure_html}"
                "</div>"
                "<div class='timeline'>"
                "<h3>Message Timeline</h3>"
                f"{messages_html}"
                "</div>"
                "</section>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Eval Trace Viewer - {html.escape(report["run_id"])}</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 0;
      background: #f5f5f5;
      color: #1f2933;
    }}
    header, main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }}
    .summary {{
      background: white;
      border: 1px solid #d8dee4;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    .trace-card {{
      background: white;
      border: 1px solid #d8dee4;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    .failures {{
      background: #fff6f6;
      border: 1px solid #f4c7c7;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 16px;
    }}
    .message {{
      margin-bottom: 12px;
      border: 1px solid #d8dee4;
      border-radius: 6px;
      background: #fafbfc;
      padding: 8px 12px;
    }}
    .tool-call {{
      margin-top: 8px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e2e8f0;
      padding: 12px;
      border-radius: 6px;
      overflow-x: auto;
    }}
    ul {{
      padding-left: 20px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="summary">
      <h1>Eval Trace Viewer</h1>
      <p><strong>Run:</strong> {html.escape(report["run_id"])} ({html.escape(report["mode"])})</p>
      <p><strong>Pass rate:</strong> {report["summary"]["passed_repeats"]}/{report["summary"]["repeat_count"]}
      ({report["summary"]["pass_rate_pct"]}%)</p>
      <h2>Cases</h2>
      <ul>{''.join(nav_items)}</ul>
    </div>
  </header>
  <main>
    {''.join(sections)}
  </main>
</body>
</html>"""


def write_run_viewer(report: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    html_path = output_path / "report.html"
    html_path.write_text(render_run_viewer(report, output_path), encoding="utf-8")
    return html_path

