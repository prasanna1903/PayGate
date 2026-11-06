PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pay_group (
    pay_group_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    pay_frequency TEXT NOT NULL
        CHECK (pay_frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly')),
    max_hours_per_period REAL NOT NULL CHECK (max_hours_per_period > 0),
    max_hours_per_day REAL NOT NULL CHECK (max_hours_per_day > 0),
    ot_multiplier REAL NOT NULL CHECK (ot_multiplier >= 1)
);

CREATE TABLE IF NOT EXISTS employee (
    employee_id TEXT PRIMARY KEY NOT NULL,
    full_name TEXT NOT NULL,
    employment_type TEXT NOT NULL
        CHECK (employment_type IN ('hourly', 'salaried')),
    pay_group_id TEXT NOT NULL REFERENCES pay_group(pay_group_id),
    hire_date TEXT NOT NULL CHECK (
        date(hire_date) IS NOT NULL AND date(hire_date) = hire_date
    ),
    termination_date TEXT CHECK (
        termination_date IS NULL OR (
            date(termination_date) IS NOT NULL
            AND date(termination_date) = termination_date
        )
    ),
    base_rate_minor INTEGER NOT NULL CHECK (base_rate_minor >= 0),
    bank_account TEXT,
    bank_routing TEXT,
    tax_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'terminated')),
    effective_from TEXT NOT NULL CHECK (
        date(effective_from) IS NOT NULL AND date(effective_from) = effective_from
    ),
    effective_to TEXT CHECK (
        effective_to IS NULL OR (
            date(effective_to) IS NOT NULL AND date(effective_to) = effective_to
        )
    ),
    CHECK (termination_date IS NULL OR termination_date >= hire_date),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS pay_period (
    period_id TEXT PRIMARY KEY NOT NULL,
    start_date TEXT NOT NULL CHECK (
        date(start_date) IS NOT NULL AND date(start_date) = start_date
    ),
    end_date TEXT NOT NULL CHECK (
        date(end_date) IS NOT NULL AND date(end_date) = end_date
    ),
    status TEXT NOT NULL,
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS paygroup_period_calendar (
    pay_group_id TEXT NOT NULL REFERENCES pay_group(pay_group_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    cutoff_date TEXT NOT NULL CHECK (
        date(cutoff_date) IS NOT NULL AND date(cutoff_date) = cutoff_date
    ),
    pay_date TEXT NOT NULL CHECK (
        date(pay_date) IS NOT NULL AND date(pay_date) = pay_date
    ),
    status TEXT NOT NULL,
    PRIMARY KEY (pay_group_id, period_id)
);

CREATE TABLE IF NOT EXISTS leave_record (
    leave_id TEXT PRIMARY KEY NOT NULL,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    leave_type TEXT NOT NULL,
    start_date TEXT NOT NULL CHECK (
        date(start_date) IS NOT NULL AND date(start_date) = start_date
    ),
    end_date TEXT NOT NULL CHECK (
        date(end_date) IS NOT NULL AND date(end_date) = end_date
    ),
    days REAL NOT NULL CHECK (days > 0),
    paid_flag INTEGER NOT NULL CHECK (paid_flag IN (0, 1)),
    status TEXT NOT NULL,
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS time_entry (
    time_entry_id TEXT PRIMARY KEY NOT NULL,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    work_date TEXT NOT NULL CHECK (
        date(work_date) IS NOT NULL AND date(work_date) = work_date
    ),
    hours REAL NOT NULL CHECK (hours >= 0),
    entry_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'SUPERSEDED')
    ),
    submission_seq INTEGER NOT NULL CHECK (submission_seq >= 1),
    supersedes_id TEXT REFERENCES time_entry(time_entry_id),
    submitted_at TEXT CHECK (submitted_at IS NULL OR datetime(submitted_at) IS NOT NULL),
    approved_by TEXT
);

CREATE TABLE IF NOT EXISTS allowance_type (
    allowance_type_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    default_amount_minor INTEGER CHECK (
        default_amount_minor IS NULL OR default_amount_minor >= 0
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS deduction_type (
    deduction_type_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    default_amount_minor INTEGER CHECK (
        default_amount_minor IS NULL OR default_amount_minor >= 0
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS employee_allowance_eligibility (
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    allowance_type_id TEXT NOT NULL
        REFERENCES allowance_type(allowance_type_id),
    effective_from TEXT NOT NULL CHECK (
        date(effective_from) IS NOT NULL AND date(effective_from) = effective_from
    ),
    effective_to TEXT CHECK (
        effective_to IS NULL OR (
            date(effective_to) IS NOT NULL AND date(effective_to) = effective_to
        )
    ),
    PRIMARY KEY (employee_id, allowance_type_id, effective_from),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS employee_deduction_enrollment (
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    deduction_type_id TEXT NOT NULL
        REFERENCES deduction_type(deduction_type_id),
    effective_from TEXT NOT NULL CHECK (
        date(effective_from) IS NOT NULL AND date(effective_from) = effective_from
    ),
    effective_to TEXT CHECK (
        effective_to IS NULL OR (
            date(effective_to) IS NOT NULL AND date(effective_to) = effective_to
        )
    ),
    PRIMARY KEY (employee_id, deduction_type_id, effective_from),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS allowance (
    allowance_id TEXT PRIMARY KEY NOT NULL,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    allowance_type_id TEXT NOT NULL
        REFERENCES allowance_type(allowance_type_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deduction (
    deduction_id TEXT PRIMARY KEY NOT NULL,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    deduction_type_id TEXT NOT NULL
        REFERENCES deduction_type(deduction_type_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    source_leave_id TEXT REFERENCES leave_record(leave_id),
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_input (
    payroll_input_id TEXT PRIMARY KEY NOT NULL,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    regular_hours REAL NOT NULL CHECK (regular_hours >= 0),
    ot_hours REAL NOT NULL CHECK (ot_hours >= 0),
    gross_minor INTEGER NOT NULL,
    deductions_minor INTEGER NOT NULL,
    net_minor INTEGER NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('AGGREGATED', 'VALIDATED', 'BLOCKED', 'APPROVED', 'EXPORTED')),
    input_hash TEXT NOT NULL,
    UNIQUE (employee_id, period_id)
);

CREATE TABLE IF NOT EXISTS payroll_input_source (
    payroll_input_id TEXT NOT NULL
        REFERENCES payroll_input(payroll_input_id),
    source_type TEXT NOT NULL
        CHECK (source_type IN ('time_entry', 'leave_record', 'allowance', 'deduction')),
    source_id TEXT NOT NULL,
    PRIMARY KEY (payroll_input_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS validation_rule (
    rule_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('High', 'Medium', 'Critical')),
    blocking_flag INTEGER NOT NULL CHECK (blocking_flag IN (0, 1)),
    params_json TEXT NOT NULL CHECK (json_valid(params_json)),
    version INTEGER NOT NULL CHECK (version >= 1),
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS validation_run (
    run_id TEXT PRIMARY KEY NOT NULL,
    started_at TEXT NOT NULL CHECK (datetime(started_at) IS NOT NULL),
    rule_versions_json TEXT NOT NULL CHECK (json_valid(rule_versions_json)),
    params_json TEXT NOT NULL CHECK (json_valid(params_json)),
    "trigger" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval (
    approval_id TEXT PRIMARY KEY NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    approver_role TEXT NOT NULL,
    approver_id TEXT NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('APPROVED', 'REJECTED', 'WAIVED')),
    comment TEXT NOT NULL,
    decided_at TEXT NOT NULL CHECK (datetime(decided_at) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS exception (
    exception_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES validation_run(run_id),
    rule_id TEXT NOT NULL REFERENCES validation_rule(rule_id),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    employee_id TEXT REFERENCES employee(employee_id),
    period_id TEXT REFERENCES pay_period(period_id),
    severity TEXT NOT NULL CHECK (severity IN ('High', 'Medium', 'Critical')),
    status TEXT NOT NULL CHECK (
        status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'WAIVED', 'SUPERSEDED')
    ),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
    approval_id TEXT REFERENCES approval(approval_id)
);

CREATE TABLE IF NOT EXISTS payroll_export (
    export_id TEXT PRIMARY KEY NOT NULL,
    pay_group_id TEXT NOT NULL REFERENCES pay_group(pay_group_id),
    period_id TEXT NOT NULL REFERENCES pay_period(period_id),
    status TEXT NOT NULL CHECK (status IN ('CREATED', 'RELEASED')),
    line_count INTEGER NOT NULL CHECK (line_count >= 0),
    total_net_minor INTEGER NOT NULL,
    created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS payroll_export_line (
    export_id TEXT NOT NULL REFERENCES payroll_export(export_id),
    payroll_input_id TEXT NOT NULL
        REFERENCES payroll_input(payroll_input_id),
    amount_minor INTEGER NOT NULL,
    PRIMARY KEY (export_id, payroll_input_id)
);

CREATE TABLE IF NOT EXISTS state_event (
    event_id TEXT PRIMARY KEY NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL)
);

CREATE TRIGGER IF NOT EXISTS state_event_no_update
BEFORE UPDATE ON state_event
BEGIN
    SELECT RAISE(ABORT, 'state_event rows are append-only');
END;

CREATE TRIGGER IF NOT EXISTS state_event_no_delete
BEFORE DELETE ON state_event
BEGIN
    SELECT RAISE(ABORT, 'state_event rows are append-only');
END;

CREATE INDEX IF NOT EXISTS idx_employee_pay_group_status
    ON employee (pay_group_id, status);
CREATE INDEX IF NOT EXISTS idx_employee_employment_type
    ON employee (employment_type);
CREATE INDEX IF NOT EXISTS idx_time_entry_employee_period_status
    ON time_entry (employee_id, period_id, status);
CREATE INDEX IF NOT EXISTS idx_time_entry_date
    ON time_entry (work_date);
CREATE INDEX IF NOT EXISTS idx_leave_employee_period_status
    ON leave_record (employee_id, period_id, status);
CREATE INDEX IF NOT EXISTS idx_allowance_employee_period_status
    ON allowance (employee_id, period_id, status);
CREATE INDEX IF NOT EXISTS idx_deduction_employee_period_status
    ON deduction (employee_id, period_id, status);
CREATE INDEX IF NOT EXISTS idx_payroll_input_period_status
    ON payroll_input (period_id, status);
CREATE INDEX IF NOT EXISTS idx_payroll_input_source_record
    ON payroll_input_source (source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_validation_rule_active_severity
    ON validation_rule (active, severity);
CREATE INDEX IF NOT EXISTS idx_exception_rule_status
    ON exception (rule_id, status);
CREATE INDEX IF NOT EXISTS idx_exception_employee_period
    ON exception (employee_id, period_id);
CREATE INDEX IF NOT EXISTS idx_exception_approval
    ON exception (approval_id);
CREATE INDEX IF NOT EXISTS idx_approval_target
    ON approval (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_payroll_export_group_period
    ON payroll_export (pay_group_id, period_id, status);
CREATE INDEX IF NOT EXISTS idx_payroll_export_line_input
    ON payroll_export_line (payroll_input_id);
CREATE INDEX IF NOT EXISTS idx_state_event_entity
    ON state_event (entity_type, entity_id, occurred_at);
