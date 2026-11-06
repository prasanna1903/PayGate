# Ground truth

Evaluation reference data belongs in this directory and must remain separate
from the operational SQLite database. Module 3 writes anomaly labels here at
injection time as CSV; it does not create a ground-truth table in SQLite.

The generator writes `labels.csv` when `--out` is used. When generating with
the default database path, it writes a size-specific CSV here. These labels
are evaluation-only reference data: only the evaluation module may read them.
