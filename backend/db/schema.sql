PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pay_group (
    pay_group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    pay_frequency TEXT NOT NULL
        CHECK (pay_frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS employee (
    employee_id TEXT PRIMARY KEY,
    pay_group_id TEXT NOT NULL REFERENCES pay_group(pay_group_id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    hire_date TEXT NOT NULL CHECK (
        date(hire_date) IS NOT NULL AND date(hire_date) = hire_date
    ),
    termination_date TEXT CHECK (
        termination_date IS NULL OR (
            date(termination_date) IS NOT NULL AND date(termination_date) = termination_date
        )
    ),
    employment_status TEXT NOT NULL DEFAULT 'active'
        CHECK (employment_status IN ('active', 'inactive', 'terminated')),
    CHECK (termination_date IS NULL OR termination_date >= hire_date)
);

CREATE TABLE IF NOT EXISTS pay_period (
    pay_period_id TEXT PRIMARY KEY,
    start_date TEXT NOT NULL CHECK (
        date(start_date) IS NOT NULL AND date(start_date) = start_date
    ),
    end_date TEXT NOT NULL CHECK (
        date(end_date) IS NOT NULL AND date(end_date) = end_date
    ),
    pay_date TEXT NOT NULL CHECK (
        date(pay_date) IS NOT NULL AND date(pay_date) = pay_date
    ),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'closed', 'exported')),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS paygroup_period_calendar (
    pay_group_id TEXT NOT NULL REFERENCES pay_group(pay_group_id),
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    submission_deadline TEXT CHECK (
        submission_deadline IS NULL OR (
            date(submission_deadline) IS NOT NULL
            AND date(submission_deadline) = submission_deadline
        )
    ),
    PRIMARY KEY (pay_group_id, pay_period_id)
);

CREATE TABLE IF NOT EXISTS leave_record (
    leave_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    leave_type TEXT NOT NULL,
    start_date TEXT NOT NULL CHECK (
        date(start_date) IS NOT NULL AND date(start_date) = start_date
    ),
    end_date TEXT NOT NULL CHECK (
        date(end_date) IS NOT NULL AND date(end_date) = end_date
    ),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS time_entry (
    time_entry_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    work_date TEXT NOT NULL CHECK (
        date(work_date) IS NOT NULL AND date(work_date) = work_date
    ),
    worked_minutes INTEGER NOT NULL CHECK (worked_minutes >= 0),
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'approved', 'rejected', 'void')),
    UNIQUE (employee_id, work_date, time_entry_id)
);

CREATE TABLE IF NOT EXISTS allowance_type (
    allowance_type_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    default_amount_minor INTEGER CHECK (
        default_amount_minor IS NULL OR default_amount_minor >= 0
    ),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS deduction_type (
    deduction_type_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    default_amount_minor INTEGER CHECK (
        default_amount_minor IS NULL OR default_amount_minor >= 0
    ),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS employee_allowance_eligibility (
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    allowance_type_id TEXT NOT NULL REFERENCES allowance_type(allowance_type_id),
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
    deduction_type_id TEXT NOT NULL REFERENCES deduction_type(deduction_type_id),
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
    allowance_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    allowance_type_id TEXT NOT NULL REFERENCES allowance_type(allowance_type_id),
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'paid'))
);

CREATE TABLE IF NOT EXISTS deduction (
    deduction_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    deduction_type_id TEXT NOT NULL REFERENCES deduction_type(deduction_type_id),
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'paid'))
);

CREATE TABLE IF NOT EXISTS payroll_input (
    payroll_input_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    input_type TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'validated', 'blocked', 'exported'))
);

CREATE TABLE IF NOT EXISTS payroll_input_source (
    payroll_input_id TEXT NOT NULL REFERENCES payroll_input(payroll_input_id),
    time_entry_id TEXT REFERENCES time_entry(time_entry_id),
    leave_id TEXT REFERENCES leave_record(leave_id),
    allowance_id TEXT REFERENCES allowance(allowance_id),
    deduction_id TEXT REFERENCES deduction(deduction_id),
    CHECK (
        (time_entry_id IS NOT NULL) +
        (leave_id IS NOT NULL) +
        (allowance_id IS NOT NULL) +
        (deduction_id IS NOT NULL) = 1
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_input_source_time_entry
    ON payroll_input_source (payroll_input_id, time_entry_id)
    WHERE time_entry_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_input_source_leave
    ON payroll_input_source (payroll_input_id, leave_id)
    WHERE leave_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_input_source_allowance
    ON payroll_input_source (payroll_input_id, allowance_id)
    WHERE allowance_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_input_source_deduction
    ON payroll_input_source (payroll_input_id, deduction_id)
    WHERE deduction_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS validation_rule (
    validation_rule_id TEXT PRIMARY KEY,
    rule_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE IF NOT EXISTS validation_run (
    validation_run_id TEXT PRIMARY KEY,
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TEXT CHECK (started_at IS NULL OR datetime(started_at) IS NOT NULL),
    completed_at TEXT CHECK (completed_at IS NULL OR datetime(completed_at) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS exception (
    exception_id TEXT PRIMARY KEY,
    validation_run_id TEXT NOT NULL REFERENCES validation_run(validation_run_id),
    payroll_input_id TEXT REFERENCES payroll_input(payroll_input_id),
    validation_rule_id TEXT NOT NULL REFERENCES validation_rule(validation_rule_id),
    message TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'waived'))
);

CREATE TABLE IF NOT EXISTS approval (
    approval_id TEXT PRIMARY KEY,
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    validation_run_id TEXT REFERENCES validation_run(validation_run_id),
    approver TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_at TEXT CHECK (decided_at IS NULL OR datetime(decided_at) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS payroll_export (
    payroll_export_id TEXT PRIMARY KEY,
    pay_period_id TEXT NOT NULL REFERENCES pay_period(pay_period_id),
    approval_id TEXT REFERENCES approval(approval_id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'exported', 'failed')),
    created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
    exported_at TEXT CHECK (exported_at IS NULL OR datetime(exported_at) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS payroll_export_line (
    payroll_export_line_id INTEGER PRIMARY KEY,
    payroll_export_id TEXT NOT NULL REFERENCES payroll_export(payroll_export_id),
    payroll_input_id TEXT NOT NULL REFERENCES payroll_input(payroll_input_id),
    employee_id TEXT NOT NULL REFERENCES employee(employee_id),
    gross_amount_minor INTEGER NOT NULL,
    deduction_amount_minor INTEGER NOT NULL CHECK (deduction_amount_minor >= 0),
    net_amount_minor INTEGER NOT NULL,
    UNIQUE (payroll_export_id, payroll_input_id)
);

CREATE TABLE IF NOT EXISTS state_event (
    state_event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    actor TEXT,
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
    ON employee (pay_group_id, employment_status);
CREATE INDEX IF NOT EXISTS idx_pay_period_status
    ON pay_period (status);
CREATE INDEX IF NOT EXISTS idx_calendar_period_group
    ON paygroup_period_calendar (pay_period_id, pay_group_id);
CREATE INDEX IF NOT EXISTS idx_leave_employee_dates
    ON leave_record (employee_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_time_entry_employee_date_status
    ON time_entry (employee_id, work_date, status);
CREATE INDEX IF NOT EXISTS idx_allowance_employee_period_status
    ON allowance (employee_id, pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_deduction_employee_period_status
    ON deduction (employee_id, pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_payroll_input_employee_period_status
    ON payroll_input (employee_id, pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_validation_run_period_status
    ON validation_run (pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_exception_rule_status
    ON exception (validation_rule_id, status);
CREATE INDEX IF NOT EXISTS idx_exception_run_status
    ON exception (validation_run_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_period_status
    ON approval (pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_export_period_status
    ON payroll_export (pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_export_line_employee
    ON payroll_export_line (employee_id);
CREATE INDEX IF NOT EXISTS idx_state_event_entity
    ON state_event (entity_type, entity_id);
