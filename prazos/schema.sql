CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    email CITEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    senha_hash TEXT,
    perfil TEXT NOT NULL DEFAULT 'usuario' CHECK (perfil IN ('admin', 'usuario')),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    permite_google BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_login TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    provedor TEXT NOT NULL CHECK (provedor IN ('senha', 'google')),
    maquina TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_em TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessoes_expira_idx ON sessoes (expira_em);
CREATE INDEX IF NOT EXISTS sessoes_usuario_idx ON sessoes (usuario_id);

CREATE TABLE IF NOT EXISTS tentativas_login (
    email CITEXT PRIMARY KEY,
    falhas TIMESTAMPTZ[] NOT NULL DEFAULT '{}',
    bloqueado_ate TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS coletas (
    id SERIAL PRIMARY KEY,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    usuario_id INTEGER REFERENCES usuarios(id),
    maquina TEXT,
    referencia DATE NOT NULL,
    updated_at_txt TEXT NOT NULL,
    updated_iso TEXT,
    runtime TEXT,
    dias JSONB NOT NULL,
    contagens JSONB NOT NULL,
    google JSONB
);

CREATE TABLE IF NOT EXISTS prazos (
    id BIGSERIAL PRIMARY KEY,
    coleta_id INTEGER NOT NULL REFERENCES coletas(id) ON DELETE CASCADE,
    chave TEXT NOT NULL,
    sistema TEXT NOT NULL,
    processo TEXT NOT NULL,
    data_final DATE,
    status TEXT,
    procurador TEXT,
    dados JSONB NOT NULL
);
ALTER TABLE coletas ADD COLUMN IF NOT EXISTS updated_iso TEXT;
CREATE INDEX IF NOT EXISTS prazos_coleta_idx ON prazos (coleta_id);
CREATE INDEX IF NOT EXISTS prazos_processo_idx ON prazos (processo);
