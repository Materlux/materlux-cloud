-- 006: marca de envio do lembrete automático de 24h (evita enviar duas vezes).
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) ANTES do deploy.

ALTER TABLE medical.appointments
    ADD COLUMN IF NOT EXISTS lembrete_enviado_em timestamptz;

COMMENT ON COLUMN medical.appointments.lembrete_enviado_em IS
    'Quando o lembrete automático (véspera da consulta, via WhatsApp) foi enviado. '
    'NULL = ainda não enviado. Preenchido pelo job POST /tasks/lembretes.';
