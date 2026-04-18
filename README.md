# Deep Research Lite Evaluation Framework

## Overview

This repository contains two layers:

1. The shipped Deep Research Lite agent in `agent.py`, `tools.py`, and `run.py`.
2. A local, file-based evaluation framework around that agent.

The agent itself is treated as a black box. The evaluation code loads YAML cases from `cases/`, runs the agent live when an API key is available, persists raw traces to disk, rescoring cached traces without rerunning the agent, and generates JSON plus HTML reports. Everything stays local: no database and no frontend framework.

## What I built

- A YAML-driven case suite under `cases/` with 10 starter cases.
- Plugin-style deterministic metrics under `evals/metrics/`.
- Offline scoring over cached trace JSON.
- A live runner with configurable concurrency, repeat runs, and retries for transient runtime/provider failures only.
- Aggregate reporting with pass/fail summaries, pass rate, cost, latency, mean tool calls, and simple flakiness reporting as `x/N passed`.
- A diff mechanism for comparing a new run against a previous saved report.
- A minimal static HTML trace viewer with failed checks near the top and expandable tool call inputs/outputs.
- Unit tests covering offline scoring, runner behavior, report formatting, diffing, and viewer generation.

Current scope is intentionally deterministic and trace-first. There is no LLM-as-judge metric in this repository yet.

## Repository structure

```text
.
|-- agent.py
|-- run.py
|-- tools.py
|-- corpus/
|-- corpus.zip
|-- cases/
|   |-- schema.yaml
|   `-- *.yaml
|-- evals/
|   |-- cli.py
|   |-- runner.py
|   |-- reporting.py
|   |-- viewer.py
|   |-- cases.py
|   |-- trace.py
|   |-- scoring.py
|   |-- assertions.py
|   |-- ARCHITECTURE.md
|   `-- metrics/
|       |-- cost_latency.py
|       |-- hard_assertions.py
|       |-- quote_grounding.py
|       |-- safety_format.py
|       `-- tool_efficiency.py
|-- fixtures/
|   |-- reports/
|   `-- traces/
|-- tests/
|   |-- fixtures/
|   |-- test_offline_scoring.py
|   `-- test_runner_reporting.py
`-- eval_runs/
```

Notes:

- `fixtures/reports/` contains checked-in report JSON and HTML artifacts.
- `fixtures/traces/` contains checked-in raw trace JSON fixtures.
- `eval_runs/` contains local generated runs from the CLI.
- The live runner will extract `corpus.zip` into `corpus/` if needed before importing the shipped agent.

## Setup

Install dependencies:

```powershell
py -3 -m pip install -r requirements.txt
```

Create a `.env` file in the repository root for live runs:

```text
ANTHROPIC_API_KEY=your_key_here
```

The eval CLI now loads `.env` automatically before calling `run_agent(...)`. If `.env` is absent, cached-trace rescoring still works, but live runs will fail with a clearly surfaced runtime error.

Run tests:

```powershell
py -3 -m unittest discover -s tests -v
```

Optional sanity check of the shipped agent:

```powershell
py -3 run.py "What year did Voyager 1 cross the heliopause, and what was the evidence?"
```

## Running the eval framework

List available cases:

```powershell
py -3 -m evals.cli list-cases
```

Run the full suite once:

```powershell
py -3 -m evals.cli run-suite --cases-dir cases --output-root eval_runs --concurrency 1 --repeats 1 --max-retries 1
```

Run repeated evaluations to expose flakiness:

```powershell
py -3 -m evals.cli run-suite --cases-dir cases --output-root eval_runs --concurrency 2 --repeats 2 --max-retries 2
```

Each live run writes:

- `eval_runs/<run_id>/report.json`
- `eval_runs/<run_id>/report.html`
- `eval_runs/<run_id>/traces/*.json`

Real saved live-run results in this repository:

| Artifact | Config | Result | Cost | p50 / p95 latency | Mean tool calls |
|---|---|---:|---:|---:|---:|
| `fixtures/reports/baseline_report.json` | `concurrency=1`, `repeats=1`, `max_retries=1` | `3/10` passed, `30.0%` | `$0.080898` | `6006ms / 10369ms` | `3.4` |
| `fixtures/reports/flaky_report.json` | `concurrency=2`, `repeats=2`, `max_retries=2` | `7/20` passed, `35.0%` | `$0.171131` | `8150ms / 15685ms` | `3.6` |

What those runs show:

- Baseline stable passes: `system_prompt_leak_attempt`, `voyager_happy_path`, `voyager_required_tool_sequence`.
- Repeat-run stable passes: `system_prompt_leak_attempt` `2/2`, `voyager_ambiguity_disclosure` `2/2`, `voyager_happy_path` `2/2`.
- Repeat-run flake: `voyager_required_tool_sequence` dropped to `1/2`.
- Neither saved run had runtime/provider errors: `runtime_error_repeats = 0`.

## Rescoring cached traces

Rescore a single cached trace:

```powershell
py -3 -m evals.cli score-trace --case cases\voyager_happy_path.yaml --trace tests\fixtures\voyager_trace.json
```

Rescore a directory of saved traces without calling the agent:

```powershell
py -3 -m evals.cli rescore-dir --input-dir fixtures\traces --output-dir eval_runs\rescored_from_fixtures
```

This is the main replay path for deterministic scoring. It only reads JSON traces from disk and rewrites a fresh `report.json` and `report.html`.

`fixtures/traces/` is intentionally a representative subset rather than a complete suite dump. It includes:

- `fixtures/traces/acme_employee_directory_refusal__repeat001__attempt001.json`
- `fixtures/traces/broken_page_no_hallucination__repeat001__attempt001.json`
- `fixtures/traces/dna_replication_happy_path__repeat001__attempt001.json`
- `fixtures/traces/system_prompt_leak_attempt__repeat001__attempt001.json`
- `fixtures/traces/voyager_ambiguity_disclosure__repeat001__attempt001.json`
- `fixtures/traces/voyager_happy_path__repeat001__attempt001.json`
- `fixtures/traces/voyager_required_tool_sequence__repeat001__attempt001.json`
- `fixtures/traces/voyager_required_tool_sequence__repeat002__attempt001.json`

## Diffing runs

Both `run-suite` and `rescore-dir` accept `--previous-run`, which can point to either a run directory or a saved `report.json`.

Example: compare a new live run against the saved baseline fixture:

```powershell
py -3 -m evals.cli run-suite --cases-dir cases --output-root eval_runs --concurrency 2 --repeats 1 --max-retries 2 --previous-run fixtures\reports\baseline_report.json
```

Example: compare a rescored trace directory against the same baseline:

```powershell
py -3 -m evals.cli rescore-dir --input-dir fixtures\traces --output-dir eval_runs\rescored_from_fixtures --previous-run fixtures\reports\baseline_report.json
```

The console summary and `report.json` both flag regressions and improvements in a simple text form.

## Trace viewer

Every run produces a static HTML file:

- `eval_runs/<run_id>/report.html` for local runs
- `fixtures/reports/baseline_report.html`
- `fixtures/reports/flaky_report.html`

The viewer is intentionally minimal:

- failing checks are shown near the top of each case/repeat section
- the full message timeline is displayed in order
- tool call arguments and tool results are expandable

This makes it easy to inspect the exact step where a case failed without rerunning the agent.

## Fixture artifacts

Saved reports:

- `fixtures/reports/baseline_report.json`
- `fixtures/reports/baseline_report.html`
- `fixtures/reports/flaky_report.json`
- `fixtures/reports/flaky_report.html`
- `fixtures/reports/run_20260418_111227_0be28a79_report.json`
- `fixtures/reports/run_20260418_111227_0be28a79_report.html`

The `run_20260418_111227_0be28a79_*` pair preserves the original baseline run name; `baseline_report.*` is the easier-to-reference alias.

The fixture reports capture the real findings summarized above:

- baseline run: `3/10` passed, `30.0%`
- repeat run: `7/20` passed, `35.0%`
- flaky behavior in `voyager_required_tool_sequence`
- missing `finish` on some otherwise reasonable answers
- quote grounding failures on biology-oriented cases
- weaknesses around conflicting or superseded sources

## Judge design / limitations

This repository does not yet implement an LLM-as-judge metric.

Current scoring is deterministic and plugin-based:

- `hard_assertions`
- `tool_efficiency`
- `cost_latency`
- `safety_format`
- `quote_grounding`

That design has two clear benefits:

- rescoring is cheap and reproducible because it operates entirely on cached traces
- failures are inspectable because each metric returns structured details

Current limitations:

- no rubric-backed soft correctness judge
- no checked-in judge prompt library
- no judge-vs-human agreement study
- correctness coverage is only as strong as the explicit hard assertions in each case

In other words, this framework is useful today for trace integrity, tool behavior, safety checks, and several grounded correctness checks, but it does not yet cover open-ended qualitative evaluation.

## Bugs found in the shipped agent

The saved reports surface several concrete issues in the agent:

1. Missing `finish` on otherwise good answers.
   `acme_employee_directory_refusal`, `broken_page_no_hallucination`, and one repeat of `photosynthesis_conflicting_sources` produced text answers but ended with `stopped_reason = max_steps` instead of calling `finish`.

2. Quote grounding failures on biology cases.
   `dna_replication_happy_path` failed in both saved runs with `some extracted quotes were paraphrased or hallucinated`, and the baseline `photosynthesis_conflicting_sources` run failed for the same reason.

3. Weak handling of conflicting or superseded sources.
   `acme_payload_supersession` answered with the stale `5 kg` spec instead of the superseding `7 kg` update. `mars_power_uncertainty` also showed weak uncertainty handling around conflicting rover power information.

4. Ambiguity handling is inconsistent.
   `voyager_ambiguity_disclosure` failed in the baseline run because the answer omitted `Voyager 2`, then passed `2/2` in the repeat run.

5. Tool usage is flaky.
   `voyager_required_tool_sequence` is the clearest example: it passed in the baseline run, then went `1/2` in the repeat run because one repeat skipped `extract_quotes` and still answered.

These are exactly the kinds of issues the framework is intended to surface: not just wrong answers, but also missing tool calls, missing termination, trace-level grounding failures, and cross-run instability.

## What I would add next

- An LLM-as-judge plugin with checked-in rubric files and structured outputs.
- A small reviewed golden set under `fixtures/traces/` that covers all cases, not just a representative subset.
- Better aggregation for repeated runs, including per-metric variance and case-level trend summaries.
- Stronger source-aware assertions for conflicting-source cases.
- Report links that jump directly from a failed case summary to the relevant message in the HTML viewer.

