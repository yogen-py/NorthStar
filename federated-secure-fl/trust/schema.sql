-- Trust Database Schema — Phase 4
-- Table: client_trust
-- Tracks per-client trust scores, participation metadata, and baseline norm.

CREATE TABLE IF NOT EXISTS client_trust (
    client_id            TEXT PRIMARY KEY,
    trust_score          REAL    DEFAULT 0.8,
    anomaly_count        INTEGER DEFAULT 0,
    rounds_participated  INTEGER DEFAULT 0,
    baseline_norm        REAL    DEFAULT 0.0,
    last_update          TIMESTAMP
);
