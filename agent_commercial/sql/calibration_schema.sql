-- ARVIS ThresholdCalibrator Schema
-- Idempotent table definitions for adaptive baseline learning and threshold calibrations.

-- 1. Daily statistical digest for healthy operational baselines
CREATE TABLE IF NOT EXISTS point_baselines (
    building_id      TEXT DEFAULT 'default' NOT NULL,
    point_id         TEXT NOT NULL,
    equipment_id     TEXT NOT NULL,
    equipment_type   TEXT NOT NULL,      -- chiller, ahu, vav, fcu, ct
    point_type       TEXT NOT NULL,      -- chwst, valve, zone_temp, co2, ...
    location         TEXT,               -- floor/zone for locality fallback
    date             TEXT NOT NULL,      -- YYYY-MM-DD (sim or wall time)
    sample_count     INTEGER NOT NULL,
    mean_val         REAL NOT NULL,
    std_val          REAL NOT NULL,
    median_val       REAL NOT NULL,      -- robust center
    mad_val          REAL NOT NULL,      -- median absolute deviation (robust scale)
    p05_val          REAL NOT NULL,
    p95_val          REAL NOT NULL,
    min_val          REAL NOT NULL,
    max_val          REAL NOT NULL,
    alarm_duration_s INTEGER DEFAULT 0,
    is_healthy       INTEGER DEFAULT 1,  -- filter flag, set by digest builder
    PRIMARY KEY (building_id, point_id, date)
);

CREATE INDEX IF NOT EXISTS idx_pb_eqtype_date ON point_baselines(building_id, equipment_type, point_type, date);
CREATE INDEX IF NOT EXISTS idx_pb_eqid_date  ON point_baselines(building_id, equipment_id, date);

-- 2. Learned thresholds with promotion audit and shadow testing
CREATE TABLE IF NOT EXISTS point_calibrations (
    building_id          TEXT DEFAULT 'default' NOT NULL,
    scope_key            TEXT NOT NULL,      -- "point:CH-01/CHWST" | "eq:CH-01" | "type:zone_temp"
    scope_level          TEXT NOT NULL,      -- "point" | "equipment" | "type"
    point_type           TEXT NOT NULL,
    equipment_type       TEXT,
    calibrated_floor     REAL NOT NULL,      -- learned standard deviation (σ) floor
    calibrated_z_thresh  REAL NOT NULL,      -- per-scope Z-score trigger
    prev_floor           REAL,               -- audit rollback floor
    prev_z_thresh        REAL,               -- audit rollback Z-threshold
    sample_size_days     INTEGER NOT NULL,
    rejection_rate_7d    REAL,               -- shadow test result
    fp_target            REAL DEFAULT 0.001, -- target daily FP rate used to derive Z
    promoted             INTEGER DEFAULT 0,  -- 0=shadow, 1=active
    change_reason        TEXT,               -- "scheduled" | "manual" | "rollback" | "bootstrap"
    last_calibrated_at   TEXT NOT NULL,
    last_promoted_at     TEXT,
    next_due_at          TEXT,
    PRIMARY KEY (building_id, scope_key)
);

CREATE INDEX IF NOT EXISTS idx_pc_eqtype ON point_calibrations(building_id, equipment_type, point_type);

-- 3. Execution history ledger for calibration runs
CREATE TABLE IF NOT EXISTS calibration_runs (
    run_id               TEXT PRIMARY KEY,   -- ULID/UUID
    building_id          TEXT DEFAULT 'default' NOT NULL,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    trigger_source       TEXT NOT NULL,      -- scheduled | manual | bootstrap | rollback
    window_days          INTEGER NOT NULL,
    rows_scanned         INTEGER,
    rows_rejected_alarm  INTEGER,
    rows_rejected_hampel INTEGER,
    scopes_updated       INTEGER,
    scopes_rolled_back   INTEGER,
    notes                TEXT
);


-- 4. Terminal Advisory Store — persistent registry of critical advisories
-- Once ARVIS issues a terminal advisory (severity=critical, equipment failure
-- imminent, life safety, regulatory non-compliance), the advisory MUST remain
-- visible to every subsequent swarm turn until explicitly acknowledged. Stops
-- operators from talking ARVIS out of critical findings. Drives escalation
-- chain on prolonged non-acknowledgement.
CREATE TABLE IF NOT EXISTS terminal_advisories (
    advisory_id          TEXT PRIMARY KEY,                 -- ulid
    building_id          TEXT NOT NULL DEFAULT 'default',
    equipment_id         TEXT,                              -- target equipment if applicable
    advisory_type        TEXT NOT NULL,                     -- equipment_failure | life_safety | energy_critical | compliance_breach | physics_violation
    severity             TEXT NOT NULL,                     -- critical | severe | high
    title                TEXT NOT NULL,                     -- short label e.g. "CH-04 bearing degradation"
    message              TEXT NOT NULL,                     -- full advisory body
    evidence_ids         TEXT NOT NULL DEFAULT '[]',        -- JSON array of plan.evidence IDs that triggered
    confidence           REAL NOT NULL DEFAULT 0.5,
    fired_at             TEXT NOT NULL,                     -- ISO timestamp
    sim_day              INTEGER,                            -- sim_day at fire time (for prove-it)
    last_surfaced_at     TEXT NOT NULL,                     -- bumped every turn it appears in context
    surface_count        INTEGER NOT NULL DEFAULT 1,        -- how many turns it's been pushed forward
    state                TEXT NOT NULL DEFAULT 'active',    -- active | acknowledged | resolved | expired
    acknowledged_at      TEXT,
    acknowledged_by      TEXT,                              -- operator id / name
    ack_signal           TEXT,                              -- the phrase that triggered ack
    resolved_at          TEXT,
    resolution_action    TEXT,                              -- "maintenance completed" / "physical inspection cleared"
    escalated_at         TEXT,                              -- when 4h+ unack escalation fired
    escalation_target    TEXT,                              -- "asset_owner_sms" / "fm_lead_email"
    source_plan_id       TEXT,                              -- queen plan_id that produced it
    source_query         TEXT                                -- operator query that triggered
);
CREATE INDEX IF NOT EXISTS idx_terminal_state ON terminal_advisories(building_id, state, fired_at);
CREATE INDEX IF NOT EXISTS idx_terminal_eq    ON terminal_advisories(equipment_id, state);


-- 5. Terminal Advisory Audit Trail — every state change recorded for compliance
CREATE TABLE IF NOT EXISTS terminal_advisory_events (
    event_id         TEXT PRIMARY KEY,
    advisory_id      TEXT NOT NULL,
    event_type       TEXT NOT NULL,                          -- fired | surfaced | acknowledged | escalated | resolved | expired
    event_at         TEXT NOT NULL,
    actor            TEXT,                                    -- "queen" | operator name | "auto_escalator"
    details          TEXT,                                    -- JSON blob
    FOREIGN KEY (advisory_id) REFERENCES terminal_advisories(advisory_id)
);
CREATE INDEX IF NOT EXISTS idx_terminal_events ON terminal_advisory_events(advisory_id, event_at);
