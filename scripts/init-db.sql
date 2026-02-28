-- ═══════════════════════════════════════════════════════════════════════════════
-- ARVIS Ops Copilot - Database Initialization Script
-- ═══════════════════════════════════════════════════════════════════════════════
-- This script initializes the PostgreSQL database for ARVIS commercial deployment
-- ═══════════════════════════════════════════════════════════════════════════════

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text similarity search

-- ═══════════════════════════════════════════════════════════════════════════════
-- Equipment Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Equipment registry
CREATE TABLE IF NOT EXISTS equipment (
    equipment_id VARCHAR(100) PRIMARY KEY,
    equipment_type VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    zone VARCHAR(100),
    floor VARCHAR(50),
    building VARCHAR(100),
    parent_equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    status VARCHAR(20) DEFAULT 'UNKNOWN',
    commissioning_date TIMESTAMP,
    last_maintenance_date TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Equipment points (sensors, setpoints)
CREATE TABLE IF NOT EXISTS equipment_points (
    point_id VARCHAR(200) PRIMARY KEY,
    equipment_id VARCHAR(100) NOT NULL REFERENCES equipment(equipment_id),
    point_type VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    unit VARCHAR(50),
    value DOUBLE PRECISION,
    quality VARCHAR(20) DEFAULT 'UNKNOWN',
    timestamp TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for equipment
CREATE INDEX IF NOT EXISTS idx_equipment_type ON equipment(equipment_type);
CREATE INDEX IF NOT EXISTS idx_equipment_zone ON equipment(zone);
CREATE INDEX IF NOT EXISTS idx_equipment_parent ON equipment(parent_equipment_id);
CREATE INDEX IF NOT EXISTS idx_point_equipment ON equipment_points(equipment_id);
CREATE INDEX IF NOT EXISTS idx_point_timestamp ON equipment_points(timestamp);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Alarm Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Active alarms
CREATE TABLE IF NOT EXISTS alarms (
    alarm_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    alarm_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT,
    state VARCHAR(20) DEFAULT 'ACTIVE',
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMP,
    acknowledged_by VARCHAR(100),
    resolved_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Alarm history
CREATE TABLE IF NOT EXISTS alarm_history (
    id SERIAL PRIMARY KEY,
    alarm_id UUID,
    equipment_id VARCHAR(100),
    alarm_type VARCHAR(100),
    severity VARCHAR(20),
    message TEXT,
    state VARCHAR(20),
    triggered_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    acknowledged_by VARCHAR(100),
    resolved_at TIMESTAMP,
    duration_seconds INTEGER,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for alarms
CREATE INDEX IF NOT EXISTS idx_alarm_equipment ON alarms(equipment_id);
CREATE INDEX IF NOT EXISTS idx_alarm_severity ON alarms(severity);
CREATE INDEX IF NOT EXISTS idx_alarm_state ON alarms(state);
CREATE INDEX IF NOT EXISTS idx_alarm_triggered ON alarms(triggered_at);
CREATE INDEX IF NOT EXISTS idx_alarm_history_equipment ON alarm_history(equipment_id);
CREATE INDEX IF NOT EXISTS idx_alarm_history_triggered ON alarm_history(triggered_at);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Energy Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Energy consumption
CREATE TABLE IF NOT EXISTS energy_consumption (
    id SERIAL PRIMARY KEY,
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    timestamp TIMESTAMP NOT NULL,
    power_kw DOUBLE PRECISION,
    energy_kwh DOUBLE PRECISION,
    demand_kw DOUBLE PRECISION,
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(equipment_id, timestamp, source)
);

-- Energy costs
CREATE TABLE IF NOT EXISTS energy_costs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    cost_qar DOUBLE PRECISION,
    tariff_type VARCHAR(50),
    peak_demand_kw DOUBLE PRECISION,
    off_peak_kwh DOUBLE PRECISION,
    peak_kwh DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for energy
CREATE INDEX IF NOT EXISTS idx_energy_equipment ON energy_consumption(equipment_id);
CREATE INDEX IF NOT EXISTS idx_energy_timestamp ON energy_consumption(timestamp);
CREATE INDEX IF NOT EXISTS idx_energy_costs_timestamp ON energy_costs(timestamp);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Maintenance Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Maintenance records
CREATE TABLE IF NOT EXISTS maintenance_records (
    id SERIAL PRIMARY KEY,
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    maintenance_type VARCHAR(50) NOT NULL,
    description TEXT,
    performed_by VARCHAR(100),
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    next_maintenance_date TIMESTAMP,
    cost_qar DOUBLE PRECISION,
    parts_replaced JSONB DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Predictive maintenance predictions
CREATE TABLE IF NOT EXISTS maintenance_predictions (
    id SERIAL PRIMARY KEY,
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    prediction_type VARCHAR(50) NOT NULL,
    predicted_failure_date TIMESTAMP,
    confidence DOUBLE PRECISION,
    remaining_useful_life_days INTEGER,
    recommended_action TEXT,
    features JSONB DEFAULT '{}',
    model_version VARCHAR(50),
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for maintenance
CREATE INDEX IF NOT EXISTS idx_maintenance_equipment ON maintenance_records(equipment_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_date ON maintenance_records(performed_at);
CREATE INDEX IF NOT EXISTS idx_prediction_equipment ON maintenance_predictions(equipment_id);
CREATE INDEX IF NOT EXISTS idx_prediction_date ON maintenance_predictions(predicted_failure_date);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Advisory Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Advisory recommendations
CREATE TABLE IF NOT EXISTS advisories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    advisory_type VARCHAR(50) NOT NULL,
    priority VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    recommendation TEXT,
    potential_savings_qar DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    implemented_at TIMESTAMP
);

-- Advisory feedback
CREATE TABLE IF NOT EXISTS advisory_feedback (
    id SERIAL PRIMARY KEY,
    advisory_id UUID REFERENCES advisories(id),
    feedback_type VARCHAR(50) NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    actual_savings_qar DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for advisories
CREATE INDEX IF NOT EXISTS idx_advisory_equipment ON advisories(equipment_id);
CREATE INDEX IF NOT EXISTS idx_advisory_status ON advisories(status);
CREATE INDEX IF NOT EXISTS idx_advisory_priority ON advisories(priority);
CREATE INDEX IF NOT EXISTS idx_advisory_feedback ON advisory_feedback(advisory_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- GSAS (Sustainability) Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- GSAS metrics
CREATE TABLE IF NOT EXISTS gsas_metrics (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    value DOUBLE PRECISION,
    unit VARCHAR(50),
    target_value DOUBLE PRECISION,
    score DOUBLE PRECISION,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- GSAS reports
CREATE TABLE IF NOT EXISTS gsas_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_type VARCHAR(50) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    overall_score DOUBLE PRECISION,
    energy_score DOUBLE PRECISION,
    water_score DOUBLE PRECISION,
    indoor_environment_score DOUBLE PRECISION,
    carbon_footprint_kg DOUBLE PRECISION,
    recommendations JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for GSAS
CREATE INDEX IF NOT EXISTS idx_gsas_metrics_category ON gsas_metrics(category);
CREATE INDEX IF NOT EXISTS idx_gsas_metrics_period ON gsas_metrics(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_gsas_reports_period ON gsas_reports(period_start, period_end);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Audit Log Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Audit trail
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50),
    entity_id VARCHAR(200),
    action VARCHAR(50) NOT NULL,
    actor VARCHAR(100),
    old_value JSONB,
    new_value JSONB,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for audit
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(created_at);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Operator Learning Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Operator decisions
CREATE TABLE IF NOT EXISTS operator_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id VARCHAR(100) REFERENCES equipment(equipment_id),
    decision_type VARCHAR(50) NOT NULL,
    context JSONB DEFAULT '{}',
    action_taken TEXT,
    outcome VARCHAR(50),
    operator_id VARCHAR(100),
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Learned patterns
CREATE TABLE IF NOT EXISTS learned_patterns (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(50) NOT NULL,
    pattern_data JSONB NOT NULL,
    frequency INTEGER DEFAULT 1,
    confidence DOUBLE PRECISION,
    last_observed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for learning
CREATE INDEX IF NOT EXISTS idx_decision_equipment ON operator_decisions(equipment_id);
CREATE INDEX IF NOT EXISTS idx_decision_type ON operator_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_pattern_type ON learned_patterns(pattern_type);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Update Timestamp Trigger
-- ═══════════════════════════════════════════════════════════════════════════════

-- Function to update timestamp
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables with updated_at
DROP TRIGGER IF EXISTS update_equipment_timestamp ON equipment;
CREATE TRIGGER update_equipment_timestamp
    BEFORE UPDATE ON equipment
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- ═══════════════════════════════════════════════════════════════════════════════
-- Grant Permissions
-- ═══════════════════════════════════════════════════════════════════════════════

-- Grant all permissions to arvis user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO arvis;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO arvis;

-- ═══════════════════════════════════════════════════════════════════════════════
-- Initial Data
-- ═══════════════════════════════════════════════════════════════════════════════

-- Insert default building if not exists
INSERT INTO equipment (equipment_id, equipment_type, name, zone, building)
VALUES ('BUILDING-01', 'BUILDING', 'Main Building', 'ALL', 'Building A')
ON CONFLICT (equipment_id) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════════════════════
-- Completion Message
-- ═══════════════════════════════════════════════════════════════════════════════

DO $$
BEGIN
    RAISE NOTICE 'ARVIS database initialization completed successfully';
END $$;
