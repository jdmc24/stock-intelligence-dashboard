# Regulatory enrichment eval harness

A small fixture-based test suite for the tool-using regulatory enrichment
agent. It exists for two reasons:

1. **Regression catching.** When you tweak the prompt or refactor the tool
   loop, run this and you'll know within ~2 minutes whether quality
   regressed on a representative set of documents.
2. **Trace-level assertions.** The harness scores not just the final JSON
   output but the agent's behavior — *did it call the right tool? did it
   run the reflection pass?* — which is what makes the "agentic" claims
   testable rather than aspirational.

## Run it

From the `backend/` directory with the venv active:

```bash
# Real Anthropic calls (default). Costs a few cents per run.
python -m app.evals.runner

# Validate fixtures + scoring code without spending money.
python -m app.evals.runner --dry

# Iterate on one fixture.
python -m app.evals.runner --only capital_requirements_amendment

# First N only.
python -m app.evals.runner --limit 2
```

Requires `ANTHROPIC_API_KEY` in `backend/.env` (or exported) for live runs.
Exits non-zero if any check fails — drop it into CI when you're ready.

## What it does

1. Spins up an **isolated SQLite database** in a temp directory (your real
   `app.db` is untouched).
2. Seeds two **prior regulatory documents** and two **company profiles** so
   the agent's tools (`search_related_regulations`, `lookup_company_profile`)
   have realistic data to find.
3. Inserts each fixture as a raw `RegDocument` and runs the real
   `enrich_document` pipeline against it.
4. Reads back the persisted enrichment + tool-call trace.
5. Scores the output against the fixture's `expected` block.

Each fixture is one JSON file under `fixtures/`. Fixture file names that
start with `_` are treated as seed/internal and are not run.

## Fixtures

| File | What it tests |
|---|---|
| `capital_requirements_amendment.json` | High/critical severity, capital products, must call `search_related_regulations` |
| `cybersecurity_disclosure_expansion.json` | Cyber functions, broker_dealer/fintech, must call `search_related_regulations` |
| `fair_lending_guidance.json` | Medium severity (guidance, not rule), `fair_lending` function, `mortgage_lending` product |
| `bsa_aml_threshold_change.json` | `bsa_aml` function, amendment change type |
| `comment_period_extension.json` | Low severity, summary mentions extension |

Every fixture opts into `must_have_reflection_entry: true` — they will all
fail that one check until the reflection pass is wired into
`enrich_document`. That is **intentional**: the eval surfaces the gap
between the prompts already in `regulations_prompts.py`
(`REFLECTION_SYSTEM`, `build_reflection_user_prompt`) and the runtime path
that does not yet call them.

## Available scoring checks

Specified inside each fixture's `expected` block. All are optional.

| Key | Behavior |
|---|---|
| `schema_required_keys: [...]` | Listed keys must be present and non-null in the enrichment |
| `severity_in: [...]` | `severity` must be one of the values |
| `change_type_in: [...]` | `change_type` must be one of the values |
| `products_any_of: [...]` | `affected_products` must overlap by at least one |
| `functions_any_of: [...]` | `affected_functions` must overlap by at least one |
| `institution_types_any_of: [...]` | `institution_types` must overlap by at least one |
| `summary_includes_any_of_ci: [...]` | Case-insensitive substring match — at least one must appear in `summary` |
| `summary_min_words: N` | `summary` must contain at least N whitespace-separated tokens |
| `must_call_tool: "name"` | Named tool must appear at least once in the trace |
| `must_have_reflection_entry: true` | Trace must contain an entry with `name == "self_reflection"` |

## Adding a fixture

1. Drop a new JSON file in `fixtures/`. Required keys: `id`,
   `document_number`, `title`, `publication_date`, `document_type`,
   `agencies`, `raw_text`, `expected`.
2. Keep `raw_text` realistic but small — under ~1k tokens is plenty.
3. Pick **only the checks that are robust on this document**. Don't assert
   on incidental phrasing; assert on structural / enum / behavioral
   properties that will hold across model versions.

## Design notes

- **No LLM-as-judge.** All checks are deterministic. Cheaper, faster, and
  the failures point to specific, fixable causes (wrong enum, missing tool
  call) rather than fuzzy "model didn't seem confident."
- **Trace-level, not just output-level.** The `must_call_tool` and
  `must_have_reflection_entry` checks score the agent's *process*, not
  just its final answer. This is the part that's hard to fake.
- **Isolated DB.** Real prod data is not mutated. Each run gets a fresh
  temp SQLite, seeded fresh from `_seed.json`.
- **No mocking of Anthropic.** Mocks would test plumbing, not behavior.
  When you change a prompt, you want the eval to feel the change.
