-- Materlux Cloud — migração v2. Segura para rodar mais de uma vez.
-- Aplicar no Cloud SQL Studio (banco materlux), como a migração 001.

-- R3: data de nascimento da paciente (obrigatória para nota fiscal)
ALTER TABLE patients.records   ADD COLUMN IF NOT EXISTS birth_date date;

-- R6: campos financeiros lançados pela secretária na agenda
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS valor_pago numeric(10,2);
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS forma_pagamento varchar(20);
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS observacoes text;

-- índice para os relatórios por período
CREATE INDEX IF NOT EXISTS idx_appointments_start ON medical.appointments(start_time);
