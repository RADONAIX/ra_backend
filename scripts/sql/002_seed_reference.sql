-- =====================================================================
-- RADONAIX — reference seed (roles, system config, decoders, alerts).
--
-- NOTE: The canonical seeder is `python -m app.seed`, which ALSO creates
-- the demo users with bcrypt-hashed passwords (SQL cannot hash passwords).
-- Run this script only if you are provisioning without the Python seeder;
-- you must still create at least one user (via the app or seeder) to log in.
--
-- Idempotent: ON CONFLICT DO NOTHING. Run after 001_app_schema.sql.
-- =====================================================================
SET search_path TO administration, public;

-- --- Roles + permission matrices (mirror app/core/rbac.py) -----------
INSERT INTO roles (id, name, description, status, is_system, permissions) VALUES
('admin', 'Administrator',
 'Full platform access including user and role management.', 'Active', true,
 '{"dashboard":{"view":true,"edit":true},"reports":{"view":true,"edit":true},"workbench":{"view":true,"edit":true},"caseManagement":{"view":true,"edit":true},"pipelines":{"view":true,"edit":true},"userManagement":{"view":true,"edit":true},"roleManagement":{"view":true,"edit":true},"settings":{"view":true,"edit":true}}'::jsonb),
('ra_lead', 'RA Manager',
 'Oversees assurance operations, pipelines, reports and cases.', 'Active', true,
 '{"dashboard":{"view":true,"edit":true},"reports":{"view":true,"edit":true},"workbench":{"view":true,"edit":true},"caseManagement":{"view":true,"edit":true},"pipelines":{"view":true,"edit":true},"userManagement":{"view":false,"edit":false},"roleManagement":{"view":false,"edit":false},"settings":{"view":true,"edit":false}}'::jsonb),
('analyst', 'RA Analyst',
 'Investigates leakage cases and works the assurance workbench.', 'Active', true,
 '{"dashboard":{"view":true,"edit":false},"reports":{"view":true,"edit":false},"workbench":{"view":true,"edit":true},"caseManagement":{"view":true,"edit":true},"pipelines":{"view":true,"edit":false},"userManagement":{"view":false,"edit":false},"roleManagement":{"view":false,"edit":false},"settings":{"view":false,"edit":false}}'::jsonb),
('viewer', 'Report Viewer',
 'Read-only access to dashboards, reports and pipelines.', 'Active', true,
 '{"dashboard":{"view":true,"edit":false},"reports":{"view":true,"edit":false},"workbench":{"view":false,"edit":false},"caseManagement":{"view":false,"edit":false},"pipelines":{"view":true,"edit":false},"userManagement":{"view":false,"edit":false},"roleManagement":{"view":false,"edit":false},"settings":{"view":false,"edit":false}}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- --- Singleton system config -----------------------------------------
INSERT INTO system_config (id, environment, retention_days, sla_minutes, alert_email, maintenance_mode)
VALUES ('system', 'production', 365, 15, 'ops-alerts@radonaix.io', false)
ON CONFLICT (id) DO NOTHING;

-- --- Decoders --------------------------------------------------------
INSERT INTO decoders (id, name, version, status, throughput) VALUES
('DEC-ASN1-v3', 'ASN.1 CDR Decoder',   '3.2.1', 'Enabled',  '12k/s'),
('DEC-JSON-v2', 'JSON Event Decoder',  '2.5.0', 'Enabled',  '28k/s'),
('DEC-CSV-v1',  'Legacy CSV Decoder',  '1.8.4', 'Disabled', '—')
ON CONFLICT (id) DO NOTHING;

-- --- Representative pipeline alerts -----------------------------------
INSERT INTO pipeline_alerts (id, severity, stage, message, status, created_at) VALUES
('ALT-2231', 'high',     'Validation',      'Schema drift on field call_duration',    'Open',         now()),
('ALT-2230', 'medium',   'Reconciliation',  'Latency above SLA (18m vs 15m)',          'Acknowledged', now()),
('ALT-2229', 'low',      'Decoding',        'Throughput degraded 4% on DEC-ASN1-v3',   'Open',         now()),
('ALT-2228', 'critical', 'File Collection', 'Source MSC-EU-3 unreachable',             'Open',         now())
ON CONFLICT (id) DO NOTHING;
