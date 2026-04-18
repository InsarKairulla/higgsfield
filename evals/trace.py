from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TraceLoadError(ValueError):
    """Raised when a trace file cannot be loaded."""


@dataclass(frozen=True)
class ToolCallRecord:
    id: str
    name: str
    args: dict[str, Any]
    result: Any
    assistant_message_index: int
    tool_message_index: int | None


@dataclass(frozen=True)
class Trace:
    raw: dict[str, Any]
    source_path: Path | None = None

    @classmethod
    def from_path(cls, path: str | Path) -> "Trace":
        trace_path = Path(path)
        try:
            raw = json.loads(trace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TraceLoadError(f"{trace_path} is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise TraceLoadError(f"{trace_path} must contain a JSON object")
        return cls(raw=raw, source_path=trace_path)

    @property
    def run_id(self) -> str:
        return str(self.raw.get("run_id") or "")

    @property
    def question(self) -> str:
        return str(self.raw.get("question") or "")

    @property
    def error(self) -> str | None:
        value = self.raw.get("error")
        return None if value is None else str(value)

    @property
    def eval_metadata(self) -> dict[str, Any]:
        value = self.raw.get("eval") or {}
        return value if isinstance(value, dict) else {}

    @property
    def messages(self) -> list[dict[str, Any]]:
        value = self.raw.get("messages") or []
        return value if isinstance(value, list) else []

    @property
    def final_answer(self) -> str:
        return str(self.raw.get("final_answer") or "")

    @property
    def citations(self) -> list[str]:
        value = self.raw.get("citations") or []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    @property
    def stopped_reason(self) -> str:
        return str(self.raw.get("stopped_reason") or "")

    @property
    def cost_usd(self) -> float:
        value = self.raw.get("cost_usd", 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @property
    def wall_time_ms(self) -> int:
        value = self.raw.get("wall_time_ms", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @property
    def total_tokens(self) -> dict[str, int]:
        value = self.raw.get("total_tokens") or {}
        if not isinstance(value, dict):
            return {"input": 0, "output": 0}
        try:
            return {
                "input": int(value.get("input", 0)),
                "output": int(value.get("output", 0)),
            }
        except (TypeError, ValueError):
            return {"input": 0, "output": 0}

    def get(self, path: str) -> Any:
        if not path:
            return self.raw
        current: Any = self.raw
        for segment in path.split("."):
            if isinstance(current, dict):
                if segment not in current:
                    raise KeyError(path)
                current = current[segment]
                continue
            if isinstance(current, list):
                if not segment.isdigit():
                    raise KeyError(path)
                index = int(segment)
                if index < 0 or index >= len(current):
                    raise KeyError(path)
                current = current[index]
                continue
            raise KeyError(path)
        return current

    def tool_calls(self, name: str | None = None) -> list[ToolCallRecord]:
        tool_results: dict[str, tuple[int, Any]] = {}
        for index, message in enumerate(self.messages):
            if message.get("role") != "tool":
                continue
            tool_use_id = str(message.get("tool_use_id") or "")
            if tool_use_id:
                tool_results[tool_use_id] = (index, message.get("content"))

        calls: list[ToolCallRecord] = []
        for assistant_index, message in enumerate(self.messages):
            if message.get("role") != "assistant":
                continue
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                call_name = str(tool_call.get("name") or "")
                if name is not None and call_name != name:
                    continue
                call_id = str(tool_call.get("id") or "")
                tool_result_index, tool_result = tool_results.get(call_id, (None, None))
                args = tool_call.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                calls.append(
                    ToolCallRecord(
                        id=call_id,
                        name=call_name,
                        args=args,
                        result=tool_result,
                        assistant_message_index=assistant_index,
                        tool_message_index=tool_result_index,
                    )
                )
        return calls

    def tool_call_names(self) -> list[str]:
        return [call.name for call in self.tool_calls()]

    def tool_call_count(self) -> int:
        return len(self.tool_calls())

    def fetched_urls(self) -> set[str]:
        return {
            str(call.args.get("url"))
            for call in self.tool_calls("fetch_url")
            if "url" in call.args
        }

    def answer_word_count(self) -> int:
        return len(re.findall(r"\S+", self.final_answer))

    def tool_errors(self) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for call in self.tool_calls():
            if isinstance(call.result, dict) and "error" in call.result:
                errors.append(
                    {"tool": call.name, "tool_use_id": call.id, "error": call.result["error"]}
                )
        return errors
