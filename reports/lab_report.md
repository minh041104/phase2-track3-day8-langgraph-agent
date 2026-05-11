# Day 08 Lab Report - LangGraph Agentic Orchestration

## 1. Team / student

- Name: Nguyen Binh Minh - 2A202600137
- Repo/commit: phase2-track3-day8-langgraph-agent
- Date: 2026-05-11

## 2. Architecture

This lab implements a production-style LangGraph workflow for a support-ticket
agent. The graph is built as a `StateGraph` with explicit node boundaries,
conditional routing, a bounded retry loop, human approval for risky actions,
checkpoint configuration, and scenario-level metrics.

The main execution path is:

```text
START -> intake -> classify -> conditional route
```

After classification, the graph follows one of five routes:

| Route | Graph path | Purpose |
|---|---|---|
| simple | answer -> finalize -> END | Answer safe FAQ-style requests directly. |
| tool | tool -> evaluate -> answer -> finalize -> END | Use the mock tool for lookup/status requests. |
| missing_info | clarify -> finalize -> END | Ask a clarification question instead of guessing. |
| risky | risky_action -> approval -> tool -> evaluate -> answer -> finalize -> END | Require approval before external or destructive actions. |
| error | retry -> tool -> evaluate -> retry/answer/dead_letter | Demonstrate bounded recovery from transient failures. |

All paths terminate through `finalize -> END`. The retry path is bounded by
`max_attempts`, so error scenarios cannot loop forever.

## 3. State schema

The state is intentionally lean and serializable. Fields that represent the
latest decision are overwritten, while audit-style fields are append-only.

| Field | Reducer | Why |
|---|---|---|
| thread_id | overwrite | Stable checkpoint key for each scenario run. |
| scenario_id | overwrite | Used to connect final state to metrics. |
| query | overwrite | Normalized support-ticket text. |
| route | overwrite | Current classified route. |
| risk_level | overwrite | Current risk assessment for the request. |
| attempt | overwrite | Retry counter used by the bounded retry loop. |
| max_attempts | overwrite | Per-scenario retry limit. |
| final_answer | overwrite | Final answer returned to the user. |
| pending_question | overwrite | Clarification question for vague requests. |
| proposed_action | overwrite | Risky action prepared for approval. |
| approval | overwrite | Latest approval decision. |
| evaluation_result | overwrite | Gate used by `route_after_evaluate`. |
| messages | append | Compact audit trail of agent messages. |
| tool_results | append | Preserve tool evidence across retries. |
| errors | append | Preserve retry and failure evidence. |
| events | append | Full node-level audit trail for grading and debugging. |

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

## 5. Scenario results

Metrics were generated from `outputs/metrics.json`.

| Scenario | Expected route | Actual route | Success | Nodes | Retries | Interrupts |
|---|---|---|---:|---:|---:|---:|
| S01_simple | simple | simple | yes | 4 | 0 | 0 |
| S02_tool | tool | tool | yes | 6 | 0 | 0 |
| S03_missing | missing_info | missing_info | yes | 4 | 0 | 0 |
| S04_risky | risky | risky | yes | 8 | 0 | 1 |
| S05_error | error | error | yes | 10 | 2 | 0 |
| S06_delete | risky | risky | yes | 8 | 0 | 1 |
| S07_dead_letter | error | error | yes | 5 | 1 | 0 |

Summary:

- Total scenarios: 7
- Success rate: 100.00%
- Average nodes visited: 6.43
- Total retries: 3
- Total approval/interrupt events: 2
- Resume success flag: false

## 6. Failure analysis

### Tool failure and retry

Error-route scenarios start at the `retry` node. The retry node increments
`attempt`, then routes to `tool` while `attempt < max_attempts`. The mock tool
returns an `ERROR` result for transient failures. `evaluate_node` reads the
latest tool result and sets `evaluation_result` to `needs_retry`, causing the
graph to route back to `retry`.

Scenario `S05_error` demonstrates successful recovery. It records two retry
events and then completes with a final answer after the tool result becomes
successful.

### Dead letter escalation

Scenario `S07_dead_letter` sets `max_attempts` to 1. After the first retry,
`route_after_retry` detects that the retry limit has been reached and sends the
run to `dead_letter`. The dead-letter node returns a manual-review response
instead of continuing to loop.

### Risky action approval

Risky requests such as refunds, deletes, and outbound email actions are routed
through `risky_action -> approval` before tool execution. The default lab
implementation uses mock approval so tests and CI can run offline. If approval
is rejected, `route_after_approval` sends the run to clarification instead of
executing the action.

## 7. Persistence / recovery evidence

The CLI builds a checkpointer from `configs/lab.yaml` and invokes each scenario
with a stable `thread_id`:

```python
run_config = {"configurable": {"thread_id": state["thread_id"]}}
final_state = graph.invoke(state, config=run_config)
```

The default configuration uses the in-memory checkpointer:

```yaml
checkpointer: memory
```

SQLite persistence has also been implemented as an extension path in
`persistence.py`. It creates a SQLite connection, enables WAL mode, and passes
the connection to `SqliteSaver`. To enable it locally, update `configs/lab.yaml`
to:

```yaml
checkpointer: sqlite
database_url: checkpoints.db
```

This allows LangGraph checkpoints to survive process restarts when the SQLite
extra dependency is installed.

## 8. Tests and validation

The following checks were run successfully:

```text
python -m pytest -p no:cacheprovider
11 passed

python -m ruff check src tests --no-cache
All checks passed

python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json
Metrics valid. success_rate=100.00%
```

The local Windows PowerShell environment does not currently provide the `make`
command, so the equivalent Python commands were used directly.

## 9. Extension work

Completed extension work:

- SQLite checkpointer support using `sqlite3.connect(...)` and WAL mode.
- Explainable classification events that record matched routing keywords.
- Richer generated report content with architecture, state schema, metrics,
  failure analysis, and persistence notes.
- Lint cleanup so `ruff check src tests` passes.

## 10. Improvement plan

If given one more day, I would productionize the following areas first:

1. Replace string-based mock tool results with structured payloads containing
   status, data, error type, and retryability.
2. Add real human-in-the-loop resume handling using LangGraph interrupts and a
   small approval UI.
3. Add state-history inspection or time-travel replay with `get_state_history()`
   to demonstrate recovery from checkpoints.
4. Export a Mermaid graph diagram and include it in the final demo.
5. Add more hidden-style tests for keyword conflicts, approval rejection, and
   max-retry edge cases.

## 11. Additional hidden scenario validation

I also tested the graph with `data/sample/scenarios_hidden.jsonl`. This file
contains 15 additional scenarios covering simple answers, tool lookups,
missing-information requests, risky approval paths, retryable errors,
dead-letter escalation, and mixed-priority routing.

Results from `outputs/metrics_hidden.json`:

- Total hidden scenarios: 15
- Success rate: 100.00%
- Average nodes visited: 6.60
- Total retries: 5
- Total approval/interrupt events: 5

The mixed-priority scenario `G15_mixed` is especially useful for validating the
routing policy. Its query is "Check refund status for order 456", which contains
both tool keywords (`check`, `status`, `order`) and a risky keyword (`refund`).
The graph correctly routed it to `risky`, proving that the classifier prioritizes
approval-required actions over tool execution.
