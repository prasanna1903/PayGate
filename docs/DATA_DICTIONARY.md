# PayGate Data Dictionary

This dictionary describes the 21 operational tables in
[`backend/db/schema.sql`](../backend/db/schema.sql). Column names, SQLite
types, nullability, constraints, and indexes below describe that schema as
implemented. Where Section 7 of the PayGate Final Implementation Blueprint
specifies a requirement, it is identified as a **Blueprint requirement**.
Details present in the SQL but not specified by Section 7 are identified as
**Implementation detail**; they are not additional blueprint business rules.

## Conventions and scope

- **Required** means the column is declared `NOT NULL`; **Nullable** means it
  is not. All primary-key columns in the current schema are explicitly
  `NOT NULL`.
- A foreign key (FK) is enforced when the connection has SQLite foreign-key
  enforcement enabled. The schema script issues `PRAGMA foreign_keys = ON`;
  connections opened elsewhere must also enable it.
- Dates are `TEXT` in ISO `YYYY-MM-DD` form. The schema checks date columns
  with SQLite `date()` and requires the parsed value to equal the stored text.
  Timestamp columns are `TEXT` checked with SQLite `datetime()` where
  applicable; a timezone convention is not specified.
- Money is stored as `INTEGER` minor units (for example, cents or the
  applicable smallest currency unit), not floating-point major units. The
  schema does not define a currency or its minor-unit scale. Hours and days
  are represented as `REAL`.
- `CHECK`, `UNIQUE`, defaults, and indexes below are the ones declared in the
  current schema. A status column without a `CHECK` has no status-value
  restriction in this schema; this dictionary does not invent one.
- Ground-truth data is not part of the operational database schema.

## Tables and columns

### `employee`

Blueprint fields: `employee_id` PK; full name, employment type, pay group,
hire/termination dates, base rate, optional bank and tax details, status, and
effective dates.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Required | PK | Stable employee identifier. |
| `full_name` | TEXT | Required | — | Synthetic or otherwise approved display name for the employee. |
| `employment_type` | TEXT | Required | CHECK: `hourly`, `salaried` | Employment classification. |
| `pay_group_id` | TEXT | Required | FK → `pay_group.pay_group_id` | Employee's pay group. |
| `hire_date` | TEXT | Required | Valid ISO date | Employment start date. |
| `termination_date` | TEXT | Nullable | Valid ISO date if present; on or after `hire_date` | Termination date, if applicable. |
| `base_rate_minor` | INTEGER | Required | CHECK: `>= 0` | Base compensation rate in minor units. The schema does not specify the rate's time basis. |
| `bank_account` | TEXT | Nullable | — | Bank account detail. |
| `bank_routing` | TEXT | Nullable | — | Bank routing detail. |
| `tax_id` | TEXT | Nullable | — | Tax identifier. |
| `status` | TEXT | Required | CHECK: `active`, `inactive`, `terminated` | Employee status. |
| `effective_from` | TEXT | Required | Valid ISO date | Start of the effective-dated employee record. |
| `effective_to` | TEXT | Nullable | Valid ISO date if present; on or after `effective_from` | End of the effective-dated employee record, if any. |

### `pay_group`

Blueprint fields: `pay_group_id` PK, name, pay frequency, period/day hour
limits, and overtime multiplier.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `pay_group_id` | TEXT | Required | PK | Pay-group identifier. |
| `name` | TEXT | Required | UNIQUE | Pay-group name. |
| `pay_frequency` | TEXT | Required | CHECK: `weekly`, `biweekly`, `semimonthly`, `monthly` | Pay frequency. |
| `max_hours_per_period` | REAL | Required | CHECK: `> 0` | Configured period-hour threshold. |
| `max_hours_per_day` | REAL | Required | CHECK: `> 0` | Configured daily-hour threshold. |
| `ot_multiplier` | REAL | Required | CHECK: `>= 1` | Overtime multiplier. |

The name uniqueness and the listed value/range checks are implementation
details; Section 7 does not prescribe their exact values.

### `pay_period`

Blueprint fields: `period_id` PK, start and end dates, and status.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `period_id` | TEXT | Required | PK | Pay-period identifier. |
| `start_date` | TEXT | Required | Valid ISO date | First date of the period. |
| `end_date` | TEXT | Required | Valid ISO date; on or after `start_date` | Last date of the period. |
| `status` | TEXT | Required | No status-value CHECK in this schema | Pay-period status; allowed values require clarification. |

### `paygroup_period_calendar`

Blueprint requirement: a pay-group/pay-period N:M bridge, with composite PK
and cutoff and pay dates. The schema also has a `status` column; Section 7
does not enumerate calendar status values.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `pay_group_id` | TEXT | Required | FK → `pay_group.pay_group_id`; part of composite PK | Pay group for this calendar record. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id`; part of composite PK | Pay period for this calendar record. |
| `cutoff_date` | TEXT | Required | Valid ISO date | Cutoff date for the pay-group period. |
| `pay_date` | TEXT | Required | Valid ISO date | Scheduled pay date. |
| `status` | TEXT | Required | No status-value CHECK in this schema | Calendar-record status; allowed values require clarification. |

Composite PK: (`pay_group_id`, `period_id`).

### `leave_record`

Blueprint fields: leave identifier, employee and period FKs, leave details,
dates, days, paid flag, and status.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `leave_id` | TEXT | Required | PK | Leave-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee associated with leave. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id` | Pay period associated with leave. |
| `leave_type` | TEXT | Required | — | Leave category; values are not specified by Section 7 or constrained in this schema. |
| `start_date` | TEXT | Required | Valid ISO date | First date of leave. |
| `end_date` | TEXT | Required | Valid ISO date; on or after `start_date` | Last date of leave. |
| `days` | REAL | Required | CHECK: `> 0` | Number of leave days. |
| `paid_flag` | INTEGER | Required | CHECK: `0` or `1` | Whether the leave is paid. |
| `status` | TEXT | Required | No status-value CHECK in this schema | Leave status; allowed values require clarification. |

### `time_entry`

Blueprint lifecycle: `DRAFT` → `SUBMITTED` → `APPROVED` or `REJECTED`;
`APPROVED` → `SUPERSEDED` on correction. The schema constrains the status
value set but does not enforce transitions between values.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `time_entry_id` | TEXT | Required | PK | Time-entry identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee who worked the recorded time. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id` | Pay period containing the entry. |
| `work_date` | TEXT | Required | Valid ISO date | Date worked. |
| `hours` | REAL | Required | CHECK: `>= 0` | Hours recorded. |
| `entry_type` | TEXT | Required | — | Entry category; allowed values are not specified. |
| `status` | TEXT | Required | CHECK: `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, `SUPERSEDED` | Time-entry lifecycle status. |
| `submission_seq` | INTEGER | Required | CHECK: `>= 1` | Sequence number for a submission. |
| `supersedes_id` | TEXT | Nullable | FK → `time_entry.time_entry_id` | Prior entry replaced by this correction, if any. |
| `submitted_at` | TEXT | Nullable | SQLite `datetime()` accepted if present | Submission timestamp. |
| `approved_by` | TEXT | Nullable | — | Identifier of the approver; no FK target is specified. |

### `allowance_type`

Section 7 specifies this as a catalog but does not list its columns. These
columns are implementation details from the current schema.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `allowance_type_id` | TEXT | Required | PK | Allowance-type identifier. |
| `name` | TEXT | Required | UNIQUE | Allowance-type name. |
| `default_amount_minor` | INTEGER | Nullable | CHECK: null or `>= 0` | Optional default amount in minor units. |
| `status` | TEXT | Required | Default `active`; CHECK: `active`, `inactive` | Catalog-record status. |

### `deduction_type`

Section 7 specifies this as a catalog but does not list its columns. These
columns are implementation details from the current schema.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `deduction_type_id` | TEXT | Required | PK | Deduction-type identifier. |
| `name` | TEXT | Required | UNIQUE | Deduction-type name. |
| `default_amount_minor` | INTEGER | Nullable | CHECK: null or `>= 0` | Optional default amount in minor units. |
| `status` | TEXT | Required | Default `active`; CHECK: `active`, `inactive` | Catalog-record status. |

### `employee_allowance_eligibility`

Blueprint requirement: an employee-to-allowance-type bridge with effective
dates. The schema defines a composite primary key as an implementation choice.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Required | FK → `employee.employee_id`; part of composite PK | Employee covered by the eligibility record. |
| `allowance_type_id` | TEXT | Required | FK → `allowance_type.allowance_type_id`; part of composite PK | Allowance type covered by the record. |
| `effective_from` | TEXT | Required | Valid ISO date; part of composite PK | First effective date. |
| `effective_to` | TEXT | Nullable | Valid ISO date if present; on or after `effective_from` | Last effective date, if any. |

Composite PK: (`employee_id`, `allowance_type_id`, `effective_from`).

### `employee_deduction_enrollment`

Blueprint requirement: an employee-to-deduction-type bridge with effective
dates. The schema defines a composite primary key as an implementation choice.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Required | FK → `employee.employee_id`; part of composite PK | Employee covered by the enrollment record. |
| `deduction_type_id` | TEXT | Required | FK → `deduction_type.deduction_type_id`; part of composite PK | Deduction type covered by the record. |
| `effective_from` | TEXT | Required | Valid ISO date; part of composite PK | First effective date. |
| `effective_to` | TEXT | Nullable | Valid ISO date if present; on or after `effective_from` | Last effective date, if any. |

Composite PK: (`employee_id`, `deduction_type_id`, `effective_from`).

### `allowance`

Blueprint fields: allowance identifier, employee/period/type FKs, amount, and
status.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `allowance_id` | TEXT | Required | PK | Allowance-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee receiving the allowance. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id` | Pay period associated with the allowance. |
| `allowance_type_id` | TEXT | Required | FK → `allowance_type.allowance_type_id` | Allowance category. |
| `amount_minor` | INTEGER | Required | CHECK: `>= 0` | Allowance amount in minor units. |
| `status` | TEXT | Required | No status-value CHECK in this schema | Allowance status; allowed values require clarification. |

### `deduction`

Blueprint fields: deduction identifier, employee/period/type FKs, amount,
optional source leave FK, and status.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `deduction_id` | TEXT | Required | PK | Deduction-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee for whom the deduction is recorded. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id` | Pay period associated with the deduction. |
| `deduction_type_id` | TEXT | Required | FK → `deduction_type.deduction_type_id` | Deduction category. |
| `amount_minor` | INTEGER | Required | CHECK: `>= 0` | Deduction amount in minor units. |
| `source_leave_id` | TEXT | Nullable | FK → `leave_record.leave_id` | Leave record that sourced this deduction, if applicable. |
| `status` | TEXT | Required | No status-value CHECK in this schema | Deduction status; allowed values require clarification. |

### `payroll_input`

Blueprint fields include employee and period FKs, hours and monetary totals,
status and input hash, with one input per employee and period. The blueprint
lifecycles are `AGGREGATED` → `VALIDATED` or `BLOCKED` → `APPROVED` →
`EXPORTED`. The schema permits these status values but does not enforce
transitions.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `payroll_input_id` | TEXT | Required | PK | Payroll-input identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id`; UNIQUE with `period_id` | Employee for whom payroll is prepared. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id`; UNIQUE with `employee_id` | Pay period for this input. |
| `regular_hours` | REAL | Required | CHECK: `>= 0` | Aggregated regular hours. |
| `ot_hours` | REAL | Required | CHECK: `>= 0` | Aggregated overtime hours. |
| `gross_minor` | INTEGER | Required | — | Gross amount in minor units. |
| `deductions_minor` | INTEGER | Required | — | Deduction total in minor units. |
| `net_minor` | INTEGER | Required | — | Net amount in minor units. |
| `status` | TEXT | Required | CHECK: `AGGREGATED`, `VALIDATED`, `BLOCKED`, `APPROVED`, `EXPORTED` | Payroll-input lifecycle status. |
| `input_hash` | TEXT | Required | — | Hash associated with the payroll input; algorithm and contents are not specified here. |

Table constraint: `UNIQUE (employee_id, period_id)`.

### `payroll_input_source`

Blueprint requirement: generic N:M traceability bridge between payroll inputs
and source records. Unlike a table with one nullable FK per source kind, this
schema stores the source category and its ID in a single pair of columns.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `payroll_input_id` | TEXT | Required | FK → `payroll_input.payroll_input_id`; part of composite PK | Payroll input using the source record. |
| `source_type` | TEXT | Required | CHECK: `time_entry`, `leave_record`, `allowance`, `deduction`; part of composite PK | Kind of source record. |
| `source_id` | TEXT | Required | Part of composite PK; no FK in this schema | Identifier of the source row. |

Composite PK: (`payroll_input_id`, `source_type`, `source_id`). This prevents
linking the same typed source record to the same payroll input more than once.
`source_id` has no declared FK because one generic column cannot reference
several source tables using ordinary SQLite foreign keys. Therefore the
database does not itself verify that each source ID exists or matches its
declared type; that integrity must be checked by application logic or tests.

### `validation_rule`

Blueprint fields: rule identifier, name, severity, blocking flag, parameters,
version, and active flag.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `rule_id` | TEXT | Required | PK | Validation-rule identifier. |
| `name` | TEXT | Required | — | Rule name. |
| `severity` | TEXT | Required | CHECK: `High`, `Medium`, `Critical` | Rule severity. |
| `blocking_flag` | INTEGER | Required | CHECK: `0` or `1` | Whether the rule is configured to block. |
| `params_json` | TEXT | Required | CHECK: valid JSON | Rule parameters encoded as JSON. |
| `version` | INTEGER | Required | CHECK: `>= 1` | Rule version number. |
| `active` | INTEGER | Required | CHECK: `0` or `1` | Whether the rule is active. |

The schema's severity spelling/capitalization and allowed set are
implementation details; Section 7 does not enumerate rule severity values.

### `validation_run`

Blueprint fields: run identifier, start time, rule versions, parameters, and
trigger.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `run_id` | TEXT | Required | PK | Validation-run identifier. |
| `started_at` | TEXT | Required | SQLite `datetime()` accepted | Run start timestamp. |
| `rule_versions_json` | TEXT | Required | CHECK: valid JSON | Rule versions used by the run. |
| `params_json` | TEXT | Required | CHECK: valid JSON | Parameters used by the run. |
| `trigger` | TEXT | Required | — | Trigger or cause of the run. |

The column name `trigger` is quoted in SQL because it is also a SQL keyword.

### `exception`

Blueprint fields: run and rule references, entity details, optional employee
and period, severity, status, evidence, and creation time. The schema also
supports a nullable approval link for waiver handling.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `exception_id` | TEXT | Required | PK | Exception identifier. |
| `run_id` | TEXT | Required | FK → `validation_run.run_id` | Validation run that produced the exception. |
| `rule_id` | TEXT | Required | FK → `validation_rule.rule_id` | Rule associated with the exception. |
| `entity_type` | TEXT | Required | — | Type of entity involved. |
| `entity_id` | TEXT | Required | — | Identifier of the entity involved. |
| `employee_id` | TEXT | Nullable | FK → `employee.employee_id` | Related employee, if applicable. |
| `period_id` | TEXT | Nullable | FK → `pay_period.period_id` | Related pay period, if applicable. |
| `severity` | TEXT | Required | CHECK: `High`, `Medium`, `Critical` | Exception severity. |
| `status` | TEXT | Required | CHECK: `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `WAIVED`, `SUPERSEDED` | Exception lifecycle status. |
| `evidence_json` | TEXT | Required | CHECK: valid JSON | Evidence for the finding, encoded as JSON. |
| `created_at` | TEXT | Required | SQLite `datetime()` accepted | Exception creation timestamp. |
| `approval_id` | TEXT | Nullable | FK → `approval.approval_id` | Related approval, if any; the schema does not enforce that it is specifically a waiver. |

Blueprint lifecycle: `OPEN` → `ACKNOWLEDGED` → `RESOLVED` or `WAIVED`;
`OPEN` → `SUPERSEDED` on rerun. The schema constrains values but does not
enforce transitions.

### `approval`

Blueprint fields: approval identifier, target details, approver role and
identity, decision, comment, and decision time. `target_type` and `target_id`
form a polymorphic target; no FK to the target entity is declared.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `approval_id` | TEXT | Required | PK | Approval identifier. |
| `target_type` | TEXT | Required | — | Type of entity being approved. |
| `target_id` | TEXT | Required | — | Identifier of the target entity; no FK is declared. |
| `approver_role` | TEXT | Required | — | Role of the approver. |
| `approver_id` | TEXT | Required | — | Approver identifier; no FK target is specified. |
| `decision` | TEXT | Required | CHECK: `APPROVED`, `REJECTED`, `WAIVED` | Approval decision. |
| `comment` | TEXT | Required | — | Comment associated with the decision. |
| `decided_at` | TEXT | Required | SQLite `datetime()` accepted | Decision timestamp. |

The decision values are implementation details; Section 7 does not list the
allowed values.

### `payroll_export`

Blueprint lifecycle: `CREATED` → `RELEASED`. The schema checks those values
but does not enforce transitions.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `export_id` | TEXT | Required | PK | Payroll-export identifier. |
| `pay_group_id` | TEXT | Required | FK → `pay_group.pay_group_id` | Pay group included in the export. |
| `period_id` | TEXT | Required | FK → `pay_period.period_id` | Pay period included in the export. |
| `status` | TEXT | Required | CHECK: `CREATED`, `RELEASED` | Export lifecycle status. |
| `line_count` | INTEGER | Required | CHECK: `>= 0` | Number of export lines. |
| `total_net_minor` | INTEGER | Required | — | Export net total in minor units. |
| `created_at` | TEXT | Required | SQLite `datetime()` accepted | Export creation timestamp. |

### `payroll_export_line`

Blueprint fields: export and payroll-input references, and the amount.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `export_id` | TEXT | Required | FK → `payroll_export.export_id`; part of composite PK | Export containing this line. |
| `payroll_input_id` | TEXT | Required | FK → `payroll_input.payroll_input_id`; part of composite PK | Payroll input represented by this line. |
| `amount_minor` | INTEGER | Required | — | Line amount in minor units. |

Composite PK: (`export_id`, `payroll_input_id`), an implementation detail
that also prevents the same input from appearing twice in one export.

### `state_event`

Blueprint requirement: append-only state history. The SQL enforces append-only
behavior with triggers that reject `UPDATE` and `DELETE`.

| Column | Type | Nullability | Keys and constraints | Meaning |
|---|---|---|---|---|
| `event_id` | TEXT | Required | PK | State-event identifier. |
| `entity_type` | TEXT | Required | — | Type of entity whose state changed. Allowed values are not specified. |
| `entity_id` | TEXT | Required | — | Identifier of the entity whose state changed; no FK is declared. |
| `from_state` | TEXT | Nullable | — | State before the event, if any. |
| `to_state` | TEXT | Required | — | State after the event. |
| `actor` | TEXT | Required | — | Actor associated with the change. |
| `reason` | TEXT | Required | — | Reason for the change. |
| `occurred_at` | TEXT | Required | SQLite `datetime()` accepted | Event timestamp. |

## Relationships and cardinalities

The cardinalities below follow Section 7 and the declared foreign keys. A
bridge table's composite key prevents duplicate pairs where stated.

- **PayGroup 1:N Employee**: `employee.pay_group_id` references
  `pay_group.pay_group_id`.
- **PayGroup N:M PayPeriod**: `paygroup_period_calendar` links both parents
  and uses (`pay_group_id`, `period_id`) as its primary key.
- **Employee 1:N TimeEntry and LeaveRecord**:
  `time_entry.employee_id` and `leave_record.employee_id` reference employee.
- **Employee 1:N Allowance and Deduction**: their `employee_id` columns
  reference employee.
- **Employee+Period 1:1 PayrollInput**: the input references employee and
  period, and `UNIQUE(employee_id, period_id)` permits at most one row for a
  pair.
- **PayrollInput N:M source records**: `payroll_input_source` stores one row
  per input, source type, and source ID. Its FK points to the payroll input;
  its generic `source_id` has no FK to the different possible source tables.
- **AllowanceType 1:N Allowance** and **DeductionType 1:N Deduction**: each
  transaction references one catalog type.
- **Employee N:M AllowanceType/DeductionType over time**:
  `employee_allowance_eligibility` and `employee_deduction_enrollment`
  provide effective-dated bridge records. Their respective composite keys
  include `effective_from`.
- **LeaveRecord 1:N Deduction (optional per deduction)**:
  `deduction.source_leave_id` is nullable and references a leave record.
- **ValidationRun 1:N Exception** and **ValidationRule 1:N Exception**:
  each exception references one run and one rule.
- **Approval 1:N Exception (optional per exception)**:
  `exception.approval_id` is nullable. The schema does not restrict its use
  to waivers.
- **PayrollExport 1:N PayrollExportLine**: each line references one export;
  the line's composite key allows a given payroll input once in that export.
- **PayrollInput 1:N PayrollExportLine**: each line references one input.
- **Approval targets and StateEvent entities are polymorphic**: their
  `target_type`/`target_id` or `entity_type`/`entity_id` fields do not have a
  direct FK to every possible target table.

## Uniqueness and indexes

Declared unique constraints:

- `pay_group.name`
- `allowance_type.name`
- `deduction_type.name`
- `payroll_input(employee_id, period_id)`

Composite primary keys also enforce uniqueness for
`paygroup_period_calendar(pay_group_id, period_id)`,
`employee_allowance_eligibility(employee_id, allowance_type_id, effective_from)`,
`employee_deduction_enrollment(employee_id, deduction_type_id, effective_from)`,
`payroll_input_source(payroll_input_id, source_type, source_id)`, and
`payroll_export_line(export_id, payroll_input_id)`.

Declared non-unique indexes:

| Index | Columns |
|---|---|
| `idx_employee_pay_group_status` | `employee(pay_group_id, status)` |
| `idx_employee_employment_type` | `employee(employment_type)` |
| `idx_time_entry_employee_period_status` | `time_entry(employee_id, period_id, status)` |
| `idx_time_entry_date` | `time_entry(work_date)` |
| `idx_leave_employee_period_status` | `leave_record(employee_id, period_id, status)` |
| `idx_allowance_employee_period_status` | `allowance(employee_id, period_id, status)` |
| `idx_deduction_employee_period_status` | `deduction(employee_id, period_id, status)` |
| `idx_payroll_input_period_status` | `payroll_input(period_id, status)` |
| `idx_payroll_input_source_record` | `payroll_input_source(source_type, source_id)` |
| `idx_validation_rule_active_severity` | `validation_rule(active, severity)` |
| `idx_exception_rule_status` | `exception(rule_id, status)` |
| `idx_exception_employee_period` | `exception(employee_id, period_id)` |
| `idx_exception_approval` | `exception(approval_id)` |
| `idx_approval_target` | `approval(target_type, target_id)` |
| `idx_payroll_export_group_period` | `payroll_export(pay_group_id, period_id, status)` |
| `idx_payroll_export_line_input` | `payroll_export_line(payroll_input_id)` |
| `idx_state_event_entity` | `state_event(entity_type, entity_id, occurred_at)` |

These are implementation indexes; Section 7 does not prescribe index names or
an exhaustive index list.

## Lifecycle states and enforcement

Section 7 defines these lifecycle paths:

- **TimeEntry**: `DRAFT` → `SUBMITTED` → `APPROVED` or `REJECTED`;
  `APPROVED` → `SUPERSEDED` on correction.
- **PayrollInput**: `AGGREGATED` → `VALIDATED` or `BLOCKED` →
  `APPROVED` → `EXPORTED`.
- **Exception**: `OPEN` → `ACKNOWLEDGED` → `RESOLVED` or `WAIVED`;
  `OPEN` → `SUPERSEDED` on rerun.
- **PayrollExport**: `CREATED` → `RELEASED`.

`CHECK` constraints on `time_entry`, `payroll_input`, `exception`, and
`payroll_export` restrict their status values to those shown above. These
checks do **not** enforce transition order. State changes should be recorded in
`state_event`; its triggers prevent updates and deletes to the event history.

Other `CHECK`-constrained domains and values are listed with their columns.
For status columns where the schema has no status `CHECK`, the allowed values
remain unspecified and are not inferred here.

## Ground truth boundary

The blueprint requires ground truth to remain separate from the operational
database. The schema contains no ground-truth table. Ground-truth files belong
in the separate `ground_truth/` directory, not in this database.
