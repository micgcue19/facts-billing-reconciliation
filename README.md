# FACTS Incidental Billing — Validation Pipeline

**A proof of concept: catching school billing errors before families see them.**

Built by [Equivalent Cue](https://equivalentcue.com) — data & process consulting for Gulf Coast small businesses.

Runs entirely on synthetic data. No real family information was used, at any point, for any purpose.

---

## The problem

Most of a school's tuition billing runs itself once it's set for the year. The recurring monthly work — and most of the errors — live in **incidental billing**: hot lunch, after-care, field trips, classroom fees, athletics.

Each month someone in the office gathers those charges from several places: a lunch spreadsheet, after-care sign-in sheets, field-trip envelopes, notes from teachers. They line each charge up against the right family and key it into FACTS. It's slow, it's manual, and every hand-off is a chance for a wrong bill — a fee on the wrong family, a duplicate, a fat-fingered amount, a charge for a student who withdrew in October.

Those mistakes usually surface when a parent calls.

**The bottleneck isn't FACTS. It's everything upstream of FACTS.**

---

## What this does

Three pieces that work together:

| Script | What it does |
|---|---|
| `generate_billing_data.py` | Builds a realistic fake school — roster, students, a full month of incidental charges — then deliberately seeds it with the messes a real office produces, and logs every one to an answer key. |
| `validate_billing_data.py` | Ingests the raw charges, checks every row, auto-corrects what's safe, holds what isn't, and writes a FACTS-ready import file plus an exception report. Then scores itself against the answer key. |
| `build_dashboard.py` | Renders a single self-contained HTML page: what's billable, what's held and why, dollar totals, and the office's worklist. No internet, no chart libraries — it opens offline, emails cleanly, and prints. |

---

## Verified results

Actual output from a clean run. Seed is fixed, so these numbers reproduce exactly:

```
RECONCILIATION
------------------------------------------------------------
Charge rows received:            425
  duplicate lines removed:       2
  billable (clean + fixed):      408
  held for office review:        15
Billable total:                  $30,815.50

SCORECARD  --  vs error_manifest.csv
------------------------------------------------------------
Planted errors:        27
Caught:                27
Missed:                0
False positives:       0  (wrongly blocked from billing)

Result: PASS
```

**Twenty-seven planted errors, twenty-seven caught, none missed, and not one good charge wrongly blocked.**

That last number matters as much as the first. A validator that catches everything by holding everything is useless — it just moves the manual work rather than removing it. The false-positive count is the proof it didn't cheat.

---

## Why the answer key matters

Most "I built a validation script" claims are unfalsifiable. This one isn't.

The generator writes four files, not one:

- `charges_dirty.csv` — the messy input, what an office would actually hand you
- `charges_clean.csv` — the same data done correctly
- `error_manifest.csv` — every planted error, its type, and how it should be fixed
- `families.csv` — the roster, complete with a duplicated family

The validator never sees the clean file or the manifest while it works. It runs blind, then scores itself afterward. That turns "I wrote a script" into "here is proof it catches exactly what was planted — no more, no fewer."

---

## How it decides: two dispositions

Every finding lands in one of two buckets. This split is the whole idea.

**Billed (auto-corrected)** — safe to fix without asking anyone:
- Date formats normalized to ISO (`03/05/2026`, `March 5, 2026`, `3-5-26` → `2026-03-05`)
- Stray whitespace and inconsistent casing in names
- Currency symbols stripped from amounts
- Exact duplicate lines removed

**Held (needs office)** — will not be billed until a human resolves it:
- Missing or unparseable amounts
- Implausible amounts — negative, zero, or outside the fee schedule's range
- Unknown charge codes, or a code that doesn't match its description
- Charges for a family not on the roster
- Charges for a withdrawn family

The safe stuff flows through untouched. The risky stuff stops **before** a family gets a wrong bill — with a logged reason attached for the annual audit.

---

## Quickstart

```bash
pip install -r requirements.txt

python generate_billing_data.py   # writes output/ — roster, dirty charges, answer key, manifest
python validate_billing_data.py   # writes facts_ready_import.csv + exception_report.csv, prints the scorecard
python build_dashboard.py         # writes output/dashboard.html
```

Then open `output/dashboard.html` in any browser.

Requires Python 3.9+ and pandas. Nothing else — no internet, no API keys, no database.

---

## What's in `output/`

Committed deliberately, so the results are browsable without running anything.

| File | What it is |
|---|---|
| `families.csv` | The roster handed to you, duplicate family included |
| `charges_dirty.csv` | Raw monthly charges — the input |
| `charges_clean.csv` | The answer key |
| `error_manifest.csv` | Every planted error and its expected fix |
| `facts_ready_import.csv` | Clean, normalized, billable rows |
| `exception_report.csv` | The audit trail — every row touched, why, and what was done |
| `dashboard.html` | The reconciliation view |

---

## Adapting it to another school

The generator is a template engine, not a one-off. `CONFIG` at the top of `generate_billing_data.py` controls the school name, family count, billing month, random seed, and how many of each error type to inject:

```python
school_b = dict(CONFIG)
school_b.update(school_name="Example Academy", seed=7,
                num_families=90, output_dir="output_school_b")
generate(school_b)
```

A second school is a config change, not a rewrite. That's what makes this replicable across a diocese rather than a favor done once.

For real use, the only school-specific work is mapping `facts_ready_import.csv`'s columns onto that school's actual FACTS incidental-billing import template, and reconciling `FEE_SCHEDULE` against their real fee codes and ranges.

---

## How data is handled

This demonstration uses only synthetic, generated data.

On real engagements: data stays in the client's environment. Processed on their machine or their own cloud, nothing copied off-site, nothing retained after the job is done, deleted on request. The tool prepares data to go *into* FACTS — it does not replace FACTS and does not transmit anything on its own.

---

## License

Copyright © 2026 Equivalent Cue LLC. All rights reserved.

This repository is published so the work can be read and evaluated. It is not open source: no licence is granted to copy, modify or redistribute the code or data. See `LICENSE`. For permission, write to **hello@equivalentcue.com**.

---

## About

Built by Equivalent Cue LLC — data and process consulting for small businesses on the Mississippi Gulf Coast.

Not IT consulting. The work is finding the data an organization already has, and putting it to work: cleaning it up, checking it, and cutting out the manual steps between where it lives and where it needs to go.

**equivalentcue.com** · **hello@equivalentcue.com**
