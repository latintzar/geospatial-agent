"""
Planning Tool - Force Agent to Think Before Acting
===================================================

A simple tool that forces the Agent to articulate its plan before executing.
Displays "Thinking..." logic in the UI so users see the reasoning.

Usage:
    plan = create_execution_plan(
        steps=["Define AOI for Berlin", "Query Matrix for wealth + transit", "Search for competitors"],
        rationale="User wants site selection - applying Retail Expansion playbook"
    )
"""

from typing import List


def create_execution_plan(steps: List[str], rationale: str) -> str:
    """
    Force the Agent to think before acting.
    
    This tool doesn't fetch data - it returns a formatted plan string.
    Call this FIRST for complex multi-step queries.
    
    Args:
        steps: List of planned actions in order
        rationale: Why this approach makes sense
    
    Returns:
        Formatted plan string for display
    """
    plan_lines = [f"**Reasoning:** {rationale}", "", "**Execution Plan:**"]
    for i, step in enumerate(steps, 1):
        plan_lines.append(f"  {i}. {step}")
    
    return "\n".join(plan_lines)


# Tool wrapper for agent registration
def tool_create_plan(steps: List[str], rationale: str) -> dict:
    """
    Display your thinking process before executing.
    
    Use this for complex queries to show your reasoning.
    
    Args:
        steps: Ordered list of actions you will take
        rationale: Why this approach answers the user's question
    
    Returns:
        Plan display (no data fetched)
    """
    plan_text = create_execution_plan(steps, rationale)
    return {
        "success": True,
        "plan": plan_text,
        "steps": steps,
        "rationale": rationale,
    }
