-- 007: Plataforma "Fertilidade Sem Segredos" — matching médico ↔ paciente por
-- proximidade (raio configurável, padrão 100 km). Site fertilidadesemsegredos.com.br
-- servido pelo MESMO Cloud Run (roteado por Host). Público, sem login.
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) ANTES do deploy.

CREATE SCHEMA IF NOT EXISTS fertilidade;

-- Médicos que se cadastram para receber indicações de leitoras do livro.
-- Entram como 'pendente' e só aparecem na busca após aprovação manual da Materlux.
CREATE TABLE IF NOT EXISTS fertilidade.medicos (
    id            serial PRIMARY KEY,
    nome          text NOT NULL,
    crm           text NOT NULL,
    especialidade text,
    telefone      text,
    email         text,
    cep           text,
    endereco      text,             -- logradouro
    numero        text,
    complemento   text,
    bairro        text,
    cidade        text,
    estado        text,             -- UF
    observacoes   text,
    latitude      double precision, -- preenchido por geocodificação no cadastro
    longitude     double precision,
    status        text NOT NULL DEFAULT 'pendente',  -- pendente | aprovado | rejeitado
    created_at    timestamptz NOT NULL DEFAULT now(),
    approved_at   timestamptz
);

CREATE INDEX IF NOT EXISTS medicos_status_idx ON fertilidade.medicos (status);

-- Pacientes sem médico no raio que pediram "me avise quando um médico se cadastrar".
CREATE TABLE IF NOT EXISTS fertilidade.pacientes_espera (
    id            serial PRIMARY KEY,
    nome          text NOT NULL,
    telefone      text NOT NULL,
    email         text,
    cep           text,
    cidade        text,
    estado        text,
    latitude      double precision,
    longitude     double precision,
    notificado    boolean NOT NULL DEFAULT false,
    notificado_em timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE fertilidade.medicos IS
    'Médicos cadastrados na plataforma do livro. status=aprovado aparece na busca.';
COMMENT ON TABLE fertilidade.pacientes_espera IS
    'Leitoras sem médico no raio; avisadas via WhatsApp quando um médico é aprovado perto.';
