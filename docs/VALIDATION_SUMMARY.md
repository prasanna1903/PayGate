# PayGate Dataset Validation Summary

## C:\Users\Dell\PayGate\data\module3-starter

- Result: **PASS**
- Seed: 20261022
- Employees: 200
- Time-entry + allowance + deduction rows: 6777
- Ground-truth labels: 16

| Check | Result | Detail |
|---|---|---|
| manifest file | PASS | read C:\Users\Dell\PayGate\data\module3-starter\manifest.json |
| manifest seed | PASS | seed 20261022 |
| manifest checksum coverage | PASS | 6 files are listed, including database, labels, schema, and seeds |
| manifest SHA-256 checksums | PASS | verified 6 file checksums |
| database file | PASS | found C:\Users\Dell\PayGate\data\module3-starter\paygate.db |
| operational schema tables | PASS | found all 21 operational tables |
| SQLite integrity | PASS | ok |
| foreign-key integrity | PASS | foreign keys enabled; no violations |
| primary and unique keys | PASS | no null or duplicate primary/unique keys |
| manifest row counts | PASS | all 21 table counts match |
| dataset size | PASS | starter: 200 employees |
| pay periods | PASS | three consecutive monthly periods match the manifest |
| pay groups and calendars | PASS | pay groups=6; calendar rows=18 (expected 6 and 18) |
| group-specific calendar dates | PASS | 3 of 3 periods have distinct cutoff and pay dates for all six groups |
| source catalogs | PASS | allowance types=4; deduction types=4 (expected 4 each) |
| hourly/salaried mix | PASS | hourly=60; salaried=140; expected=60/140 |
| transaction volume | PASS | 6777 time-entry, allowance, and deduction rows |
| manifest transaction target | PASS | manifest target=100000; blueprint target=100000 records |
| required ID formats | PASS | all populated identifier columns match required formats |
| identifier/entity relationships | PASS | IDs agree with their employee, date, and period |
| ISO dates and timestamps | PASS | all populated date and timestamp fields are valid |
| schema-defined lifecycle enums | PASS | all populated enum fields match schema CHECK values |
| integer minor-unit money | PASS | all populated money columns use SQLite INTEGER values |
| payroll net arithmetic | PASS | 0 inputs violate net = gross - deductions |
| payroll source aggregation | PASS | 0 payroll inputs differ from approved-source SQL aggregation |
| payroll export totals and scope | PASS | incorrect export totals=0; out-of-scope lines=0 |
| baseline export coverage | PASS | inputs without exactly one export line=0; duplicate group-period exports=0; export rows=18; not released=0 |
| payroll input source traceability | PASS | source IDs exist and agree with linked employee-period inputs |
| lifecycle history | PASS | time entries, payroll inputs, and exports have valid state histories |
| ground-truth columns | PASS | all 11 required columns are present and ordered |
| ground-truth labels and planned counts | PASS | 16 labels, 12 issue types; IDs, rule labels, decisions, severities, and counts match |
| anomaly and boundary scenarios | PASS | all 16 labelled scenarios exist in the database with the expected condition |
| duplicate anomaly coverage | PASS | all duplicate allowances, leave deductions, and hours are labelled |
| planned missing employee details | PASS | all missing bank and tax details are exactly the labelled anomalies |
| ground-truth database separation | PASS | no ground_truth table exists in the operational database |

## C:\Users\Dell\PayGate\data\module3-full

- Result: **PASS**
- Seed: 20261022
- Employees: 3000
- Time-entry + allowance + deduction rows: 102200
- Ground-truth labels: 210

| Check | Result | Detail |
|---|---|---|
| manifest file | PASS | read C:\Users\Dell\PayGate\data\module3-full\manifest.json |
| manifest seed | PASS | seed 20261022 |
| manifest checksum coverage | PASS | 6 files are listed, including database, labels, schema, and seeds |
| manifest SHA-256 checksums | PASS | verified 6 file checksums |
| database file | PASS | found C:\Users\Dell\PayGate\data\module3-full\paygate.db |
| operational schema tables | PASS | found all 21 operational tables |
| SQLite integrity | PASS | ok |
| foreign-key integrity | PASS | foreign keys enabled; no violations |
| primary and unique keys | PASS | no null or duplicate primary/unique keys |
| manifest row counts | PASS | all 21 table counts match |
| dataset size | PASS | full: 3000 employees |
| pay periods | PASS | three consecutive monthly periods match the manifest |
| pay groups and calendars | PASS | pay groups=6; calendar rows=18 (expected 6 and 18) |
| group-specific calendar dates | PASS | 3 of 3 periods have distinct cutoff and pay dates for all six groups |
| source catalogs | PASS | allowance types=4; deduction types=4 (expected 4 each) |
| hourly/salaried mix | PASS | hourly=900; salaried=2100; expected=900/2100 |
| transaction volume | PASS | 102200 time-entry, allowance, and deduction rows (expected 95,000 to 105,000 for full) |
| manifest transaction target | PASS | manifest target=100000; blueprint target=100000 records |
| required ID formats | PASS | all populated identifier columns match required formats |
| identifier/entity relationships | PASS | IDs agree with their employee, date, and period |
| ISO dates and timestamps | PASS | all populated date and timestamp fields are valid |
| schema-defined lifecycle enums | PASS | all populated enum fields match schema CHECK values |
| integer minor-unit money | PASS | all populated money columns use SQLite INTEGER values |
| payroll net arithmetic | PASS | 0 inputs violate net = gross - deductions |
| payroll source aggregation | PASS | 0 payroll inputs differ from approved-source SQL aggregation |
| payroll export totals and scope | PASS | incorrect export totals=0; out-of-scope lines=0 |
| baseline export coverage | PASS | inputs without exactly one export line=0; duplicate group-period exports=0; export rows=18; not released=0 |
| payroll input source traceability | PASS | source IDs exist and agree with linked employee-period inputs |
| lifecycle history | PASS | time entries, payroll inputs, and exports have valid state histories |
| ground-truth columns | PASS | all 11 required columns are present and ordered |
| ground-truth labels and planned counts | PASS | 210 labels, 12 issue types; IDs, rule labels, decisions, severities, and counts match |
| anomaly and boundary scenarios | PASS | all 210 labelled scenarios exist in the database with the expected condition |
| duplicate anomaly coverage | PASS | all duplicate allowances, leave deductions, and hours are labelled |
| planned missing employee details | PASS | all missing bank and tax details are exactly the labelled anomalies |
| ground-truth database separation | PASS | no ground_truth table exists in the operational database |

## Reproducibility

- Result: **PASS**
- Seed: 20261022
- Employees: 200
- Detail: 6 checksums are identical across two independent runs

| File | SHA-256 |
|---|---|
| backend/db/schema.sql | `92b99ce26d859032571b4a3fc315f91f07a5b97ad23e36de108c9dae5e8d79f5` |
| data/seed/allowance_types.csv | `f872c1c41e0ca8cc241f771d203075fcf2ba0edee65a2001bc1674db083b27c8` |
| data/seed/deduction_types.csv | `3dc5ccfaf60609535eefab3be5e4ccd1739e2338b77f85acbe0462c94f601412` |
| data/seed/pay_groups.csv | `670f953555fd2a696ef4a94824d15d946c78f14d49b70a017ac299a3ab16dbc9` |
| ground_truth/labels.csv | `af89ff3aa34e97997c320ec142bb1bde7924c7ebfc43bd4ee0a005ae6c757883` |
| paygate.db | `72391f2cc4564e9cd653df8c193a304213d3436e34447fdc9b925c55300ca70c` |

## Module 7 detection scorecard — starter dataset

The scorecard was calculated from validation run `RUN-000001` after running the
validation engine against a temporary copy of `data/module3-starter/paygate.db`.
The original dataset database and labels were read-only inputs and were not
modified. The dataset has 16 ground-truth rows: 13 `FLAG` planted issues and
3 `PASS` boundary controls.

| Metric | Result |
|---|---:|
| Total planted issues (`FLAG`) | 13 |
| Total detected findings (TP + FP) | 84 |
| TP | 13 |
| FP | 71 |
| FN | 0 |
| Precision | 0.1548 |
| Recall | 1.0000 |
| F1 | 0.2680 |

| Issue type | Planted | TP | FP | FN |
|---|---:|---:|---:|---:|
| Hours exceed period maximum | 3 | 3 | 0 | 0 |
| Duplicate allowance | 2 | 2 | 0 | 0 |
| Unapproved time exported | 1 | 1 | 0 | 0 |
| Leave deduction applied twice | 2 | 2 | 0 | 0 |
| Reconciliation failure | 1 | 1 | 0 | 0 |
| Missing bank details | 1 | 1 | 0 | 0 |
| Missing tax ID | 1 | 1 | 0 | 0 |
| Duplicate hours | 1 | 1 | 0 | 0 |
| Outlier hours | 1 | 1 | 0 | 0 |

The three `PASS` controls were not counted as planted issues, and none matched
a finding in this run. Of the 71 findings without an exact `FLAG` match, 27
were secondary detections in an employee-period containing another planted
issue, 44 were unlabelled findings, and none matched a `PASS` control. By rule,
the classifications were:

| Rule | Secondary detection | Unlabelled finding | Known-negative detection | Total |
|---|---:|---:|---:|---:|
| VR-004 | 1 | 0 | 0 | 1 |
| VR-005 | 26 | 42 | 0 | 68 |
| VR-011 | 0 | 2 | 0 | 2 |

These are descriptive categories only. The strict metric results above remain
13 TP, 71 FP, and 0 FN; secondary detections are not reclassified as true
positives. An unlabelled finding is an FP relative to available labels, not an
independently adjudicated error. See [TESTING.md](./TESTING.md) for matching
rules and classification precedence.
