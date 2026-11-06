# PayGate Evaluation and Testing

## Detection scorecard

The evaluation module compares ground-truth CSV labels with findings persisted
by the selected validation run. Only labels with `expected_decision=FLAG` count
as planted issues. `PASS` labels are known-negative controls; a finding matching
one counts as a false positive, not as a planted issue or a false negative.

For each matching finding:

- **TP**: one `FLAG` label matched by one finding.
- **FP**: an extra finding for an already-matched issue, a finding matching a
  known-negative `PASS` control, or a finding with no matching label.
- **FN**: a `FLAG` label without a matching finding.

Metrics use the requested formulas:

- Precision = TP / (TP + FP)
- Recall = TP / (TP + FN)
- F1 = 2 × Precision × Recall / (Precision + Recall)

Each zero denominator produces a value of `0`. `total_detected_issues` means
TP + FP, so it counts each actual finding once, including duplicate detections.
The scorecard provides metrics by rule ID, issue type, and severity. False
positives with no ground-truth issue type are assigned to `unmatched` in the
issue-type breakdown.

### Unmatched-finding classification

The scorecard separately classifies findings that do not exactly match a
`FLAG` record. These labels are descriptive only and never change TP, FP, or
FN:

- `known_negative_detection`: the finding exactly matches a `PASS` control.
- `secondary_detection`: no exact `FLAG` match exists, but the finding has the
  same non-empty employee and period IDs as another `FLAG` record. A different
  rule or entity identity is still not a true positive.
- `unlabelled_finding`: neither an exact `PASS` match nor a same-employee,
  same-period `FLAG` record exists.

An exact duplicate finding for a `FLAG` already matched remains an FP with
reason `duplicate_detection`; it is not included in this classification because
its identity does exactly match a planted record. The classification object
reports a total, counts by category, and counts by rule ID. As a result, its
total may be lower than FP when duplicate detections exist. `PASS` matches take
precedence over the same-period secondary category.

### Matching rules

A finding matches a label only when the rule ID, entity type, and entity ID
match. Employee and period IDs further constrain a match if both the finding
and label provide that context. Some existing rules do not provide all context
(for example, missing-bank findings have no period), so absent context is not
treated as a mismatch. A finding can match only one `FLAG` label; deterministic
ordering prevents multiple findings from inflating true positives. If a
finding's identity matches a `FLAG` label already matched by an earlier
finding, the extra finding is an FP. Known-negative `PASS` records are checked
after unmatched positive labels to prefer a true-positive match where identities
overlap.

The local evaluation result includes identifiers in unmatched records for
diagnosis. The HTTP scorecard redacts ground-truth and employee/entity IDs.

## Data boundaries and limitations

Ground-truth CSV files are read only by `backend.evaluation` and dataset
validation code. The evaluator reads persisted `exception` rows for a selected
`validation_run`; it does not run validation, change statuses, or write to the
database. The database is opened read-only. The latest run is selected by
`started_at` descending, then `run_id` descending. A validation run must exist
before a scorecard is available.

An unlabelled finding is counted as a false positive relative to the available
ground truth. This is a dataset-evaluation convention, not a human adjudication
that a finding is necessarily incorrect. Ground truth contains a finite set of
planted scenarios and selected negative controls; it does not label every
legitimate condition in the dataset.

The scorecard does not add an evaluation timestamp. Dataset metadata is limited
to identifier, size, employee count, and seed when those values exist in the
manifest.

## Running tests

Run the full suite with the project's virtual environment:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Evaluation unit tests use synthetic labels and temporary SQLite databases. The
starter integration test copies the starter database to a temporary directory,
runs validation on that copy, and compares its persisted findings against the
existing ground-truth file without changing either dataset file.
