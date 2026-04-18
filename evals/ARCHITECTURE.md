# Eval framework layout

This milestone keeps the layout small and easy to review:

```text
cases/
  schema.yaml               # human-readable case schema
  *.yaml                    # checked-in case files
evals/
  __init__.py
  cli.py                    # minimal offline rescoring entrypoint
  cases.py                  # YAML loader + validation
  trace.py                  # cached trace loader + helper accessors
  scoring.py                # metric registry + case scoring
  assertions.py             # reusable hard-assertion evaluator
  metrics/
    __init__.py             # auto-import built-in metric plugins
    hard_assertions.py
    tool_efficiency.py
    cost_latency.py
    safety_format.py
    quote_grounding.py
tests/
  fixtures/
    voyager_trace.json      # synthetic cached trace for scorer tests
  test_offline_scoring.py
```

Planned next, but intentionally not built in this milestone:

```text
fixtures/traces/            # cached real traces committed for replay
reports/                    # json/html run reports
evals/viewer.py             # html trace viewer generation
evals/runner.py             # live parallel execution + retries
```

The scorer is intentionally offline-first. It reads a cached trace JSON,
loads a case from `cases/*.yaml`, and scores metric plugins without calling
the agent or any judge model.

