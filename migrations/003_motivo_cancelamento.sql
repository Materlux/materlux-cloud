-- 003: motivo obrigatório de cancelamento (estudo de absenteísmo).
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) ANTES do deploy
-- do código que grava/exibe o motivo.

ALTER TABLE medical.appointments
    ADD COLUMN IF NOT EXISTS motivo_cancelamento text;

COMMENT ON COLUMN medical.appointments.motivo_cancelamento IS
    'Motivo informado no cancelamento (painel ou atendente WhatsApp). '
    'Preenchido quando status_id passa a 3 (paciente) ou 4 (clínica).';
