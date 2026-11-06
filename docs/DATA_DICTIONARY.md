# PayGate Data Dictionary

This document describes the tables, columns, declared constraints, indexes, and
relationships in [`backend/db/schema.sql`](../backend/db/schema.sql). It reflects
the SQL schema; it does not add rules that are not encoded there.

## Conventions

- **Required** means the column is declared `NOT NULL`. **Nullable** means it
  is not declared `NOT NULL`.
- A column described as **PK** is declared as a primary key. SQLite has a
  legacy behavior in ordinary rowid tables that may allow `NULL` in a
  non-`INTEGER PRIMARY KEY` column unless it is also explicitly `NOT NULL`.
  Most text ID primary keys in this schema do not say `NOT NULL`; their
  practical nullability therefore requires clarification. `payroll_export_line`
  uses `INTEGER PRIMARY KEY`, which is a SQLite rowid alias.
- `FK` identifies a foreign key and its referenced column. Foreign-key
  enforcement is enabled by the schema's `PRAGMA` for the connection executing
  the script; connections opened elsewhere must enable it too.
- `UNIQUE` and `CHECK` describe the schema constraints. Table defaults are
  recorded where present.
- Money amounts use `INTEGER` minor units (for example, cents or the
  corresponding smallest currency unit), not floating-point major units. The
  schema does not specify a currency or currency-specific minor-unit scale.
- Calendar dates are stored as `TEXT` and checked against SQLite's `date()`
  function in `YYYY-MM-DD` form. Timestamp columns are also `TEXT`, checked
  using SQLite's `datetime()` function; the schema does not specify a timezone
  convention or a single timestamp serialization format.

## Tables and columns

### `pay_group`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `pay_group_id` | TEXT | Nullable (PK caveat above) | PK | Identifier for the pay group. |
| `name` | TEXT | Required | UNIQUE | Pay-group name. |
| `pay_frequency` | TEXT | Required | CHECK: `weekly`, `biweekly`, `semimonthly`, or `monthly` | Pay frequency assigned to the group. |
| `status` | TEXT | Required | Default `active`; CHECK: `active` or `inactive` | Pay-group status. |

### `employee`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Nullable (PK caveat above) | PK | Employee identifier. |
| `pay_group_id` | TEXT | Required | FK → `pay_group.pay_group_id` | Employee's pay group. |
| `first_name` | TEXT | Required | — | Employee's first name. |
| `last_name` | TEXT | Required | — | Employee's last name. |
| `hire_date` | TEXT | Required | CHECK: valid ISO calendar date | Employee hire date. |
| `termination_date` | TEXT | Nullable | CHECK: null or valid ISO calendar date; if present, must be on or after `hire_date` | Employee termination date, if recorded. |
| `employment_status` | TEXT | Required | Default `active`; CHECK: `active`, `inactive`, or `terminated` | Employment status. |

### `pay_period`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `pay_period_id` | TEXT | Nullable (PK caveat above) | PK | Pay-period identifier. |
| `start_date` | TEXT | Required | CHECK: valid ISO calendar date | First date of the pay period. |
| `end_date` | TEXT | Required | CHECK: valid ISO calendar date; on or after `start_date` | Last date of the pay period. |
| `pay_date` | TEXT | Required | CHECK: valid ISO calendar date | Scheduled pay date. |
| `status` | TEXT | Required | Default `open`; CHECK: `open`, `closed`, or `exported` | Pay-period status. |

### `paygroup_period_calendar`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `pay_group_id` | TEXT | Required | FK → `pay_group.pay_group_id`; part of composite PK | Pay group in this calendar entry. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id`; part of composite PK | Pay period in this calendar entry. |
| `submission_deadline` | TEXT | Nullable | CHECK: null or valid ISO calendar date | Submission deadline for this pay-group/pay-period pair. |

The composite primary key is (`pay_group_id`, `pay_period_id`).

### `leave_record`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `leave_id` | TEXT | Nullable (PK caveat above) | PK | Leave-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee associated with the leave. |
| `leave_type` | TEXT | Required | — | Leave category; allowed values are not specified in the schema. |
| `start_date` | TEXT | Required | CHECK: valid ISO calendar date | First date of leave. |
| `end_date` | TEXT | Required | CHECK: valid ISO calendar date; on or after `start_date` | Last date of leave. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `approved`, `rejected`, or `cancelled` | Leave-record status. |

### `time_entry`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `time_entry_id` | TEXT | Nullable (PK caveat above) | PK | Time-entry identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee who worked the recorded time. |
| `work_date` | TEXT | Required | CHECK: valid ISO calendar date | Date the work was performed. |
| `worked_minutes` | INTEGER | Required | CHECK: `>= 0` | Number of minutes recorded. |
| `status` | TEXT | Required | Default `submitted`; CHECK: `submitted`, `approved`, `rejected`, or `void` | Time-entry status. |

The table also declares `UNIQUE (employee_id, work_date, time_entry_id)`. Since
`time_entry_id` is the primary key, this does not add a stronger uniqueness
rule than the primary key when IDs are non-null.

### `allowance_type`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `allowance_type_id` | TEXT | Nullable (PK caveat above) | PK | Allowance-type identifier. |
| `name` | TEXT | Required | UNIQUE | Allowance-type name. |
| `default_amount_minor` | INTEGER | Nullable | CHECK: null or `>= 0` | Optional default allowance amount in minor currency units. |
| `status` | TEXT | Required | Default `active`; CHECK: `active` or `inactive` | Allowance-type status. |

### `deduction_type`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `deduction_type_id` | TEXT | Nullable (PK caveat above) | PK | Deduction-type identifier. |
| `name` | TEXT | Required | UNIQUE | Deduction-type name. |
| `default_amount_minor` | INTEGER | Nullable | CHECK: null or `>= 0` | Optional default deduction amount in minor currency units. |
| `status` | TEXT | Required | Default `active`; CHECK: `active` or `inactive` | Deduction-type status. |

### `employee_allowance_eligibility`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Required | FK → `employee.employee_id`; part of composite PK | Employee covered by this eligibility record. |
| `allowance_type_id` | TEXT | Required | FK → `allowance_type.allowance_type_id`; part of composite PK | Allowance type for which the employee is eligible. |
| `effective_from` | TEXT | Required | CHECK: valid ISO calendar date; part of composite PK | First effective date of eligibility. |
| `effective_to` | TEXT | Nullable | CHECK: null or valid ISO calendar date; if present, on or after `effective_from` | Last effective date, if one is recorded. |

The composite primary key is (`employee_id`, `allowance_type_id`,
`effective_from`).

### `employee_deduction_enrollment`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `employee_id` | TEXT | Required | FK → `employee.employee_id`; part of composite PK | Employee covered by this enrollment record. |
| `deduction_type_id` | TEXT | Required | FK → `deduction_type.deduction_type_id`; part of composite PK | Deduction type in which the employee is enrolled. |
| `effective_from` | TEXT | Required | CHECK: valid ISO calendar date; part of composite PK | First effective date of enrollment. |
| `effective_to` | TEXT | Nullable | CHECK: null or valid ISO calendar date; if present, on or after `effective_from` | Last effective date, if one is recorded. |

The composite primary key is (`employee_id`, `deduction_type_id`,
`effective_from`).

### `allowance`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `allowance_id` | TEXT | Nullable (PK caveat above) | PK | Allowance-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee receiving the allowance. |
| `allowance_type_id` | TEXT | Required | FK → `allowance_type.allowance_type_id` | Allowance category. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period to which the allowance applies. |
| `amount_minor` | INTEGER | Required | CHECK: `>= 0` | Allowance amount in minor currency units. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `approved`, `rejected`, or `paid` | Allowance status. |

### `deduction`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `deduction_id` | TEXT | Nullable (PK caveat above) | PK | Deduction-record identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee subject to the deduction. |
| `deduction_type_id` | TEXT | Required | FK → `deduction_type.deduction_type_id` | Deduction category. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period to which the deduction applies. |
| `amount_minor` | INTEGER | Required | CHECK: `>= 0` | Deduction amount in minor currency units. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `approved`, `rejected`, or `paid` | Deduction status. |

### `payroll_input`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `payroll_input_id` | TEXT | Nullable (PK caveat above) | PK | Payroll-input identifier. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee to whom the input applies. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period for the input. |
| `input_type` | TEXT | Required | — | Input category; allowed values and relationship to source types require clarification. |
| `amount_minor` | INTEGER | Required | — | Input amount in minor currency units. The schema does not constrain its sign. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `validated`, `blocked`, or `exported` | Payroll-input status. |

### `payroll_input_source`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `payroll_input_id` | TEXT | Required | FK → `payroll_input.payroll_input_id` | Payroll input linked to a source record. |
| `time_entry_id` | TEXT | Nullable | FK → `time_entry.time_entry_id`; partial UNIQUE with `payroll_input_id` when non-null | Linked time entry, if this is the source. |
| `leave_id` | TEXT | Nullable | FK → `leave_record.leave_id`; partial UNIQUE with `payroll_input_id` when non-null | Linked leave record, if this is the source. |
| `allowance_id` | TEXT | Nullable | FK → `allowance.allowance_id`; partial UNIQUE with `payroll_input_id` when non-null | Linked allowance, if this is the source. |
| `deduction_id` | TEXT | Nullable | FK → `deduction.deduction_id`; partial UNIQUE with `payroll_input_id` when non-null | Linked deduction, if this is the source. |

A table-level CHECK requires exactly one of `time_entry_id`, `leave_id`,
`allowance_id`, or `deduction_id` to be non-null. Four partial unique indexes
prevent the same source ID of a given type from being linked to the same
payroll input more than once. The table declares no primary key.

### `validation_rule`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `validation_rule_id` | TEXT | Nullable (PK caveat above) | PK | Validation-rule identifier. |
| `rule_code` | TEXT | Required | UNIQUE | Stable code for the rule. |
| `name` | TEXT | Required | — | Validation-rule name. |
| `description` | TEXT | Required | — | Human-readable description of the rule. |
| `severity` | TEXT | Required | CHECK: `low`, `medium`, `high`, or `critical` | Severity assigned to the rule. |
| `status` | TEXT | Required | Default `active`; CHECK: `active` or `inactive` | Validation-rule status. |

### `validation_run`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `validation_run_id` | TEXT | Nullable (PK caveat above) | PK | Validation-run identifier. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period validated by this run. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `running`, `completed`, or `failed` | Validation-run status. |
| `started_at` | TEXT | Nullable | CHECK: null or accepted by SQLite `datetime()` | Run start timestamp. |
| `completed_at` | TEXT | Nullable | CHECK: null or accepted by SQLite `datetime()` | Run completion timestamp. |

### `exception`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `exception_id` | TEXT | Nullable (PK caveat above) | PK | Exception identifier. |
| `validation_run_id` | TEXT | Required | FK → `validation_run.validation_run_id` | Validation run that produced the exception. |
| `payroll_input_id` | TEXT | Nullable | FK → `payroll_input.payroll_input_id` | Payroll input associated with the exception, if recorded. |
| `validation_rule_id` | TEXT | Required | FK → `validation_rule.validation_rule_id` | Rule associated with the exception. |
| `message` | TEXT | Required | — | Exception details. |
| `severity` | TEXT | Required | CHECK: `low`, `medium`, `high`, or `critical` | Exception severity. |
| `status` | TEXT | Required | Default `open`; CHECK: `open`, `resolved`, or `waived` | Exception status. |

### `approval`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `approval_id` | TEXT | Nullable (PK caveat above) | PK | Approval-record identifier. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period being approved. |
| `validation_run_id` | TEXT | Nullable | FK → `validation_run.validation_run_id` | Associated validation run, if recorded. |
| `approver` | TEXT | Nullable | — | Approver identity; representation is not specified. |
| `status` | TEXT | Required | Default `pending`; CHECK: `pending`, `approved`, or `rejected` | Approval status. |
| `decided_at` | TEXT | Nullable | CHECK: null or accepted by SQLite `datetime()` | Time the approval decision was recorded. |

### `payroll_export`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `payroll_export_id` | TEXT | Nullable (PK caveat above) | PK | Payroll-export identifier. |
| `pay_period_id` | TEXT | Required | FK → `pay_period.pay_period_id` | Pay period represented by the export. |
| `approval_id` | TEXT | Nullable | FK → `approval.approval_id` | Associated approval, if recorded. |
| `status` | TEXT | Required | Default `draft`; CHECK: `draft`, `ready`, `exported`, or `failed` | Payroll-export status. |
| `created_at` | TEXT | Required | CHECK: accepted by SQLite `datetime()` | Export-record creation timestamp. |
| `exported_at` | TEXT | Nullable | CHECK: null or accepted by SQLite `datetime()` | Export completion timestamp, if recorded. |

### `payroll_export_line`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `payroll_export_line_id` | INTEGER | Required | PK (`INTEGER PRIMARY KEY`) | Row identifier for an export line. |
| `payroll_export_id` | TEXT | Required | FK → `payroll_export.payroll_export_id` | Export containing this line. |
| `payroll_input_id` | TEXT | Required | FK → `payroll_input.payroll_input_id`; UNIQUE with `payroll_export_id` | Payroll input represented by the line. |
| `employee_id` | TEXT | Required | FK → `employee.employee_id` | Employee represented by the line. |
| `gross_amount_minor` | INTEGER | Required | — | Gross amount in minor currency units. |
| `deduction_amount_minor` | INTEGER | Required | CHECK: `>= 0` | Deduction amount in minor currency units. |
| `net_amount_minor` | INTEGER | Required | — | Net amount in minor currency units. |

The table also declares `UNIQUE (payroll_export_id, payroll_input_id)`.

### `state_event`

| Column | Type | Nullability | Constraints | Business meaning |
|---|---|---|---|---|
| `state_event_id` | TEXT | Nullable (PK caveat above) | PK | State-event identifier. |
| `entity_type` | TEXT | Required | — | Type of entity whose state changed; allowed values are not specified. |
| `entity_id` | TEXT | Required | — | Identifier of the entity whose state changed. |
| `previous_state` | TEXT | Nullable | — | State before the event, if recorded. |
| `new_state` | TEXT | Required | — | State after the event. |
| `actor` | TEXT | Nullable | — | Actor associated with the event; representation is not specified. |
| `occurred_at` | TEXT | Required | CHECK: accepted by SQLite `datetime()` | Event timestamp. |

`state_event` has triggers that reject `UPDATE` and `DELETE`, preserving the
table as append-only history through ordinary SQL operations.

## Relationships

- A `pay_group` has many `employee` records. `employee.pay_group_id` references
  `pay_group.pay_group_id`.
- `paygroup_period_calendar` links pay groups and pay periods; its two foreign
  keys form its composite primary key.
- An `employee` may have many `leave_record`, `time_entry`, `allowance`, and
  `deduction` records.
- `allowance_type` and `deduction_type` describe the categories used by
  `allowance` and `deduction`. Employee eligibility and enrollment records link
  employees to those types over effective-date intervals.
- Each `allowance` and `deduction` references an employee, a type, and a pay
  period.
- Each `payroll_input` references one employee and one pay period.
  `payroll_input_source` links it to exactly one recorded source among a time
  entry, leave record, allowance, or deduction. The schema does not declare a
  composite foreign key to ensure that the linked source belongs to the same
  employee or pay period as the payroll input.
- A `validation_run` references a pay period. An `exception` references a
  validation run and validation rule, and may reference a payroll input.
- An `approval` references a pay period and may reference a validation run.
- A `payroll_export` references a pay period and may reference an approval.
  `payroll_export_line` links an export to payroll inputs and employees; a
  payroll input can appear at most once in a given export.
- `state_event` stores entity type and ID as text but has no foreign key to the
  entities it describes.

## Clarifications needed

- The schema does not define permitted `leave_type` or `input_type` values, or
  the exact relationship between payroll-input types and source types.
- The schema does not define the allowed values or identity format for
  `state_event.entity_type` or `state_event.actor`.
- The schema does not specify currency, the minor-unit scale, or a timezone
  convention for timestamps.
- The schema does not enforce that a payroll input's source belongs to the same
  employee or pay period, nor that an export line's employee matches its
  payroll input.
- Text primary-key columns are not explicitly declared `NOT NULL`. SQLite's
  legacy rowid-table behavior can permit `NULL` for such primary keys; whether
  this is intended should be clarified.
- `payroll_input_source` has no primary key. Its partial unique indexes prevent
  duplicate links by source type, but there is no declared row identifier.
