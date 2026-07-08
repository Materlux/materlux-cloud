-- 004: transbordo para atendente humano (pausa a atendente virtual por contato).
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) ANTES do deploy.

ALTER TABLE conversations.sessions
    ADD COLUMN IF NOT EXISTS atendimento_status text NOT NULL DEFAULT 'bot',
    ADD COLUMN IF NOT EXISTS pausado_em  timestamptz,
    ADD COLUMN IF NOT EXISTS pausado_por text;

ALTER TABLE conversations.sessions
    DROP CONSTRAINT IF EXISTS sessions_atendimento_status_check;
ALTER TABLE conversations.sessions
    ADD CONSTRAINT sessions_atendimento_status_check
    CHECK (atendimento_status IN ('bot', 'humano'));

COMMENT ON COLUMN conversations.sessions.atendimento_status IS
    'bot = atendente virtual responde; humano = bot em silêncio (recepção responde '
    'pelo WhatsApp da clínica). Volta a bot ao devolver no painel ou após 12h.';
