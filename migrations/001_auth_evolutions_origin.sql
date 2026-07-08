-- Materlux Cloud — migração incremental aplicada SOBRE o dump restaurado.
-- Segura para rodar mais de uma vez (IF NOT EXISTS / ON CONFLICT).
-- NÃO altera dados clínicos existentes.

-- 1) Autenticação da equipe (médico e secretária) ------------------------------
CREATE SCHEMA IF NOT EXISTS auth_app;

CREATE TABLE IF NOT EXISTS auth_app.users (
    id            bigserial PRIMARY KEY,
    username      varchar(64)  NOT NULL UNIQUE,
    full_name     varchar(255) NOT NULL,
    password_hash text         NOT NULL,
    role          varchar(20)  NOT NULL CHECK (role IN ('medico','secretaria')),
    -- vínculo opcional a um profissional da agenda (para o médico ver a sua)
    professional_id bigint,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- 2) Evoluções de prontuário (não existiam no dump) ----------------------------
-- Formato esperado pela recepção/PME: anamnese + data_registro + cpf.
CREATE TABLE IF NOT EXISTS medical.clinical_evolutions (
    id            bigserial PRIMARY KEY,
    patient_id    bigint REFERENCES patients.records(id),
    professional_id bigint REFERENCES medical.professionals(id),
    appointment_id  bigint REFERENCES medical.appointments(id),
    cpf           varchar(11),
    anamnese      text NOT NULL,
    exame_fisico  text,
    conduta       text,
    author_user_id bigint REFERENCES auth_app.users(id),
    -- rastreabilidade para a futura mesclagem do SSD recuperado
    origem        varchar(20) NOT NULL DEFAULT 'cloud'
                  CHECK (origem IN ('cloud','ssd_recuperado','salus_legado','reconstituido')),
    id_legado     text,
    data_registro timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evolutions_patient ON medical.clinical_evolutions(patient_id);
CREATE INDEX IF NOT EXISTS idx_evolutions_cpf     ON medical.clinical_evolutions(cpf);

-- 3) Rastreabilidade de origem nos agendamentos (Fase 1.5) ---------------------
-- Permite mesclar depois os dados do SSD sem duplicar nem sobrescrever.
ALTER TABLE medical.appointments
    ADD COLUMN IF NOT EXISTS origem varchar(20) NOT NULL DEFAULT 'cloud'
        CHECK (origem IN ('cloud','whatsapp','secretaria','ssd_recuperado','reconstituido'));
ALTER TABLE medical.appointments
    ADD COLUMN IF NOT EXISTS id_legado text;

-- 4) Usuários iniciais ---------------------------------------------------------
-- As senhas reais são definidas pelo script seed_users.py (hash bcrypt).
-- Este bloco só garante que os registros existam; o hash é atualizado pelo seed.
INSERT INTO auth_app.users (username, full_name, password_hash, role, professional_id)
VALUES
    ('murilo',   'Dr. Murilo Ferraz',      'PLACEHOLDER', 'medico',     1),
    ('isadora',  'Dra. Isadora Vencioneck', 'PLACEHOLDER', 'medico',     4),
    ('recepcao', 'Recepção Materlux',       'PLACEHOLDER', 'secretaria', NULL)
ON CONFLICT (username) DO NOTHING;
