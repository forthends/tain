# DEPRECATED since v0.6.0 — logic migrated to tain_agent/kernel/ and tain_agent/plugins/
"""
AgentToolsMixin — tool execution and decision logging.
"""
import json
import time as _time

from tain_agent.core.logging_config import get_logger

log = get_logger(__name__)


class AgentToolsMixin:
    """Mixin for executing tool calls from LLM responses."""

    def _execute_tool_calls(self, tool_use_blocks: list) -> list[dict]:
        """Execute tool calls from the LLM response and log decisions."""
        results = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input if isinstance(block.input, dict) else {}
            t_start = _time.monotonic()

            # Log the decision to call this tool
            decision_id = self.decision_log.record(
                context={
                    "phase": self.phase,
                    "cycle": self.cycle_count,
                },
                decision_type="tool_call",
                options_considered=[{"option": f"call {tool_name}", "input": tool_input}],
                chosen_option=tool_name,
                reasoning=f"Agent decided to use tool '{tool_name}' in phase '{self.phase}'.",
                expected_outcome=f"Tool '{tool_name}' executes successfully.",
                phase=self.phase,
            )

            # Execute the tool
            print(f"\n  🔧 调用工具: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

            # Handle tools that need the registry reference
            if tool_name == "list_available_tools":
                from tain_agent.tools.primal import list_available_tools as lat
                result = lat(self.tools)
            else:
                # Filter out keys that collide with ToolRegistry.call() signature
                filtered_input = {k: v for k, v in tool_input.items()
                                  if k not in ("tool_name", "timeout")}
                call_result = self.tools.call(tool_name, **filtered_input)
                if call_result.get("success"):
                    result = call_result["result"]
                else:
                    error_type = call_result.get("error_type", "unknown")
                    error_msg = call_result.get("error", "Unknown error")
                    if error_type == "timeout":
                        result = f"⏰ TIMEOUT: {error_msg}"
                    elif error_type == "exception":
                        result = f"💥 EXCEPTION: {error_msg}"
                    elif error_type == "not_found":
                        result = f"❓ NOT_FOUND: {error_msg}"
                    else:
                        result = f"Error: {error_msg}"

            elapsed_ms = (_time.monotonic() - t_start) * 1000

            # Include timing info if available
            timing = ""
            if call_result.get("duration_ms"):
                timing = f" [{call_result['duration_ms']:.0f}ms]"

            # Truncate for display
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + f"... ({len(result_str)} total chars)"
            print(f"  ✅ 结果{timing}: {result_str}")

            success = call_result.get("success", False)
            outcome_summary = (
                f"SUCCESS" if success
                else f"FAIL[{call_result.get('error_type', 'unknown')}]: {call_result.get('error', '')[:200]}"
            )
            self.decision_log.update_outcome(decision_id, outcome_summary)

            # Structured log entry
            log.agent(
                "tool_executed",
                tool=tool_name,
                success=success,
                elapsed_ms=round(elapsed_ms, 1),
                outcome=outcome_summary,
                cycle=self.cycle_count,
                phase=self.phase,
            )

            results.append({
                "tool_use_id": block.id,
                "content": str(result),
                "tool_name": tool_name,
            })

        return results
