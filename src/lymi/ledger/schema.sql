-- Ledger de lymi. Una fila por llamada a un modelo, sin excepcion.
-- Si una llamada no queda registrada aca, la afirmacion de ahorro no vale.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    task_id      TEXT    NOT NULL,   -- 'snake' | 'research' | 'repo'
    variant      TEXT    NOT NULL,   -- 'baseline' | 'p2-cache' | 'p3-local' | ...
    billing_mode TEXT    NOT NULL,   -- api | subscription | local  (dominante)
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',  -- running|passed|failed|error
    score        REAL,               -- calidad 0..1 segun la puerta de la tarea
    notes        TEXT,
    git_sha      TEXT                -- para reproducibilidad
);

CREATE TABLE IF NOT EXISTS calls (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT    NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq                INTEGER NOT NULL,
    ts                 TEXT    NOT NULL,
    provider           TEXT    NOT NULL,   -- anthropic | openai | ollama | claude-code
    model              TEXT    NOT NULL,
    billing_mode       TEXT    NOT NULL,
    tier               TEXT    NOT NULL,   -- frontier | small | local
    purpose            TEXT,               -- plan | distill | route | answer | judge
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL,               -- NULL = no comparable / tarifa desconocida
    latency_ms         INTEGER,
    ok                 INTEGER NOT NULL DEFAULT 1,
    error              TEXT,
    -- Semilla del control de egress (Fase 6): que salio de la maquina.
    egress             INTEGER NOT NULL DEFAULT 0,  -- 1 si el payload salio a internet
    payload_sha256     TEXT,
    payload_bytes      INTEGER,
    -- Secretos o datos personales reemplazados por marcadores antes de salir.
    redacciones        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_calls_run ON calls(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, variant);

-- Totales por corrida. La vista es la unica fuente del reporte, para que nadie
-- calcule el ahorro a mano con otra formula. Se recrea en cada apertura: es
-- derivada, y una vista vieja en una base existente seguiria usando la formula
-- vieja sin que nadie lo note.
DROP VIEW IF EXISTS run_totals;
CREATE VIEW run_totals AS
SELECT
    r.id                AS run_id,
    r.task_id,
    r.variant,
    r.billing_mode,
    r.status,
    r.score,
    COUNT(c.id)                              AS n_calls,
    COALESCE(SUM(c.input_tokens), 0)         AS input_tokens,
    COALESCE(SUM(c.output_tokens), 0)        AS output_tokens,
    COALESCE(SUM(c.cache_read_tokens), 0)    AS cache_read_tokens,
    COALESCE(SUM(c.cache_write_tokens), 0)   AS cache_write_tokens,
    -- Consumo remoto COMPLETO, cache incluida. La cache se lee y se escribe en el
    -- proveedor: cuesta dinero en modo api y cuota en suscripcion. Dejarla fuera
    -- escondia el prefijo del harness (~28-42k tokens por llamada a Claude Code).
    COALESCE(SUM(CASE WHEN c.billing_mode <> 'local'
                      THEN c.input_tokens + c.output_tokens
                           + c.cache_read_tokens + c.cache_write_tokens
                      ELSE 0 END), 0)        AS remote_tokens,
    COALESCE(SUM(CASE WHEN c.billing_mode <> 'local'
                      THEN c.cache_read_tokens + c.cache_write_tokens
                      ELSE 0 END), 0)        AS remote_cache_tokens,
    COALESCE(SUM(CASE WHEN c.billing_mode =  'local'
                      THEN c.input_tokens + c.output_tokens ELSE 0 END), 0) AS local_tokens,
    -- Un total con una sola llamada sin costo conocido no es un total: SUM
    -- ignoraria el NULL y mostraria un numero parcial como si fuera completo.
    CASE WHEN SUM(CASE WHEN c.id IS NOT NULL AND c.cost_usd IS NULL THEN 1 ELSE 0 END) > 0
         THEN NULL
         ELSE SUM(c.cost_usd) END            AS cost_usd,
    -- Cuantas llamadas quedaron sin tarifa: si esto no es 0, el costo esta incompleto.
    SUM(CASE WHEN c.cost_usd IS NULL AND c.billing_mode = 'api' THEN 1 ELSE 0 END) AS unpriced_calls,
    COALESCE(SUM(c.latency_ms), 0)           AS latency_ms,
    COALESCE(SUM(c.redacciones), 0)          AS redacciones,
    COALESCE(SUM(c.egress), 0)               AS egress_calls
FROM runs r
LEFT JOIN calls c ON c.run_id = r.id
GROUP BY r.id;
