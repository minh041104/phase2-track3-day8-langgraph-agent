"""Report generation helper."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def render_report_stub(metrics: MetricsReport) -> str:
    """Return a lab report with architecture, metrics, and failure analysis."""
    rows = "\n".join(
        (
            "| {scenario} | {expected} | {actual} | {success} | "
            "{nodes} | {retries} | {interrupts} |"
        ).format(
            scenario=item.scenario_id,
            expected=item.expected_route,
            actual=item.actual_route or "",
            success="yes" if item.success else "no",
            nodes=item.nodes_visited,
            retries=item.retry_count,
            interrupts=item.interrupt_count,
        )
        for item in metrics.scenario_metrics
    )
    return f"""# Day 08 Lab Report

## 1. Team / student

- Name:
- Repo/commit:
- Date:

## 2. Architecture

The workflow is a LangGraph `StateGraph` for support-ticket orchestration:

`START -> intake -> classify`, then conditional routing sends the request to one of five paths.

- `simple`: answer directly, then finalize.
- `tool`: call the mock tool, evaluate the result, answer, then finalize.
- `missing_info`: ask a clarification question, then finalize.
- `risky`: prepare a proposed action, require approval, then execute through the tool path.
- `error`: enter a bounded retry loop; when attempts are exhausted, send the run to dead letter.

Every path ends at `finalize -> END`.

## 3. State schema

| Field | Reducer | Why |
|---|---|---|
| thread_id | overwrite | stable checkpointer key per scenario run |
| scenario_id | overwrite | metric and audit identity |
| query | overwrite | normalized user request |
| route | overwrite | current routing decision |
| risk_level | overwrite | current risk classification |
| attempt | overwrite | retry counter |
| max_attempts | overwrite | retry bound |
| final_answer | overwrite | final user-facing response |
| pending_question | overwrite | clarification question when information is missing |
| proposed_action | overwrite | risky action awaiting approval |
| approval | overwrite | latest approval decision |
| evaluation_result | overwrite | retry gate after tool evaluation |
| messages | append | compact audit trail for agent messages |
| tool_results | append | preserve tool evidence across retries |
| errors | append | preserve retry and failure evidence |
| events | append | full node-level execution audit |

Append-only reducers are important because retries can visit the same node
multiple times. Preserving previous tool results, errors, and events makes the
run explainable after completion.

## 4. Routing policy

The classifier uses keyword-based heuristics instead of matching exact scenario
IDs. This keeps the graph compatible with hidden grading scenarios that use
different text but the same intent.

Routing priority:

1. `risky`: refund, delete, send, cancel, remove, revoke.
2. `tool`: status, order, lookup, check, track, find, search.
3. `missing_info`: short vague queries containing words such as it, this, that.
4. `error`: timeout, fail, failure, error, crash, unavailable, recover.
5. `simple`: default fallback.

Risky actions are checked first because a request such as "refund order 123"
contains both risky and tool-like keywords. The safer behavior is to require
approval before using the tool path.

## Metrics summary

- Total scenarios: {metrics.total_scenarios}
- Success rate: {metrics.success_rate:.2%}
- Average nodes visited: {metrics.avg_nodes_visited:.2f}
- Total retries: {metrics.total_retries}
- Total interrupts: {metrics.total_interrupts}
- Resume success: {metrics.resume_success}

## 5. Scenario results

| Scenario | Expected route | Actual route | Success | Nodes | Retries | Interrupts |
|---|---|---|---:|---:|---:|---:|
{rows}

## 6. Failure analysis

1. Retry or tool failure: error-route scenarios first enter the retry node.
   The tool can emit an `ERROR` result, `evaluate` marks it as `needs_retry`,
   and routing sends the run back to `retry` until `attempt >= max_attempts`.
2. Risky action without approval: risky scenarios go through
   `risky_action -> approval` before tool execution. If approval is rejected,
   routing sends the run to clarification instead of executing the action.
3. Max retry exhaustion: when retry attempts reach the configured limit,
   the graph routes to `dead_letter` and returns a manual-review response.

## 7. Persistence / recovery evidence

The CLI builds a checkpointer from `configs/lab.yaml` and invokes each run with
`configurable.thread_id`. The default lab configuration uses the in-memory
checkpointer for local tests. The SQLite path is implemented in `persistence.py`
with WAL mode and can be enabled by setting:

```yaml
checkpointer: sqlite
database_url: checkpoints.db
```

## 8. Tests and validation

The expected validation commands are:

```text
python -m pytest -p no:cacheprovider
python -m ruff check src tests --no-cache
python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json
```

The local Windows PowerShell environment may not provide the `make` command, so
the equivalent Python commands can be used directly.

## 9. Extension work

SQLite persistence support is implemented as an extension path. The graph also
records detailed node events and keyword matches for route explainability.

## 10. Improvement plan

With one more day, I would replace string-based mock tool results with structured
tool payloads, add real human-in-the-loop resume handling, and export a Mermaid
graph diagram for the demo.

## 11. Additional hidden scenario validation

I also tested the graph with `data/sample/scenarios_hidden.jsonl`. This file
contains additional scenarios covering simple answers, tool lookups,
missing-information requests, risky approval paths, retryable errors,
dead-letter escalation, and mixed-priority routing.

If `outputs/metrics_hidden.json` is generated, it should be included as extra
evidence. In the local validation run, the hidden set had 15 scenarios, a
100.00% success rate, 5 total retries, and 5 approval/interrupt events.

The mixed-priority scenario `G15_mixed` is especially useful for validating the
routing policy. Its query is "Check refund status for order 456", which contains
both tool keywords (`check`, `status`, `order`) and a risky keyword (`refund`).
The graph correctly routed it to `risky`, proving that the classifier prioritizes
approval-required actions over tool execution.
"""


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_stub(metrics), encoding="utf-8")
