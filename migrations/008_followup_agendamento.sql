-- 008: recuperação de agendamento não concluído (follow-up da Malu).
-- Marca quando uma conversa ficou com um agendamento em andamento sem concluir,
-- e quando o follow-up foi enviado (um por episódio). Rodar no Cloud SQL Studio
-- (banco materlux) ANTES do deploy.

ALTER TABLE conversations.sessions
    ADD COLUMN IF NOT EXISTS agendamento_pendente_desde timestamptz,
    ADD COLUMN IF NOT EXISTS followup_enviado_em timestamptz;

COMMENT ON COLUMN conversations.sessions.agendamento_pendente_desde IS
    'Último contato numa conversa que começou um agendamento e não concluiu '
    '(NULL = sem pendência). Base do follow-up de ~15 min.';
COMMENT ON COLUMN conversations.sessions.followup_enviado_em IS
    'Quando o follow-up de agendamento não concluído foi enviado (um por episódio).';
