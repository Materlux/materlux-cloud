-- 005: registro de partos com valor/data de pagamento (controle de faturamento).
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) ANTES do deploy.

CREATE TABLE IF NOT EXISTS medical.partos (
    id              serial PRIMARY KEY,
    patient_id      integer NOT NULL REFERENCES patients.records(id),
    professional_id integer NOT NULL REFERENCES medical.professionals(id),
    valor_pago      numeric(10,2),
    data_pagamento  date,
    observacoes     text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE medical.partos IS
    'Partos realizados. valor_pago/data_pagamento preenchidos pela secretária; '
    'entram no relatório de faturamento pela data do pagamento.';
