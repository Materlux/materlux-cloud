# Materlux Cloud — contexto do projeto (para Claude Code)

Sistema de **agendamento + prontuário** da Clínica Materlux (ginecologia, obstetrícia,
pediatria), reconstruído 100% na nuvem após a morte do SSD do servidor físico local.
Acessível por navegador. Inclui uma **atendente virtual de WhatsApp** (agente Gemini com
tool-calling) que substitui o antigo fluxo n8n de 519 nós.

> **Idioma:** responda ao Murilo em **português do Brasil**.
> **Segurança/LGPD:** dados de saúde ficam **no Brasil** (região `southamerica-east1`).
> Nunca sobrescreva backups originais. **Nunca** manuseie senhas/tokens em texto plano —
> quem cola segredos no Secret Manager e digita credenciais de banco/GitHub é o usuário.

---

## Stack

- **Backend:** FastAPI + Uvicorn (Python 3.12).
- **Banco:** PostgreSQL 18 (Cloud SQL). Driver **psycopg 3** com pool de conexões (`app/db.py`).
- **Auth:** bcrypt + JWT em cookie **httpOnly**. Dois papéis: `medico` e `secretaria`
  (a recepção usa `secretaria`). Ver `app/security.py`.
- **Agente WhatsApp:** `google-genai`, modelo **`gemini-2.5-flash`**, function/tool-calling
  (`app/agent.py`). Transporte via **Z-API** (webhook `POST /webhook/whatsapp`).
- **Frontend:** um único template `app/templates/app.html` (SPA simples, sem build).

---

## Infra Google Cloud

- **Projeto:** `mata-da-praia-workflows` · **região:** `southamerica-east1`
- **Conta operacional:** `suporte@materlux.com.br` (NÃO `murilo@...`). No Cloud Shell o
  prompt correto é `suporte@cloudshell`. `authuser=1` no console.
- **Cloud SQL:** instância `materlux-db`, banco `materlux`, usuário `postgres`.
  - IP público `34.95.237.235`; connection name
    `mata-da-praia-workflows:southamerica-east1:materlux-db`.
  - Backups automáticos habilitados. A senha do postgres foi trocada pelo usuário
    (não está aqui).
- **Cloud Run:** serviço `materlux-api`.
  - URL: `https://materlux-api-737153954505.southamerica-east1.run.app`
  - Revisão em produção quando este doc foi escrito: **`materlux-api-00008-rd4`**
    (commit `3e99e1a`).
- **Artifact Registry:**
  `southamerica-east1-docker.pkg.dev/mata-da-praia-workflows/materlux/materlux-api`
- **Secret Manager (injetados no Cloud Run como env):** `DATABASE_URL`, `JWT_SECRET`,
  `GEMINI_API_KEY`, `ZAPI_INSTANCE`, `ZAPI_TOKEN`, `ZAPI_CLIENT_TOKEN`, `WA_VERIFY_TOKEN`.
  - Env adicionais: `GEMINI_MODEL=gemini-2.5-flash`, `BOOKABLE_PROFESSIONAL_IDS=1,4`.
  - ⚠️ `app/config.py` traz `GEMINI_MODEL` default `gemini-2.0-flash`, **mas 2.0 foi
    aposentado** — o valor real vem da env `gemini-2.5-flash`. Ao mexer, mantenha 2.5+.

---

## Deploy (importante — tem um truque)

O deploy roda **no Cloud Shell do usuário** (não na máquina local). O daemon do Docker no
Cloud Shell **não consegue dar push** para o Artifact Registry ("connection refused"), então
`deploy.sh` usa o **`crane`** (userspace) para empurrar a imagem. `deploy.sh` também taggeia
a imagem com o **git short SHA** e roda `gcloud run deploy` com todos os secrets.

Fluxo de publicação:

```bash
# 1) No PC do usuário (Git Bash) — o push exige a passkey do iPhone dele:
git add -A && git commit -m "..." && git push

# 2) No Cloud Shell (conduzido via navegador; gh auth já configurado por device flow):
cd ~/materlux-cloud && git pull
python3 -m py_compile app/*.py app/routers/*.py   # checagem de sintaxe
bash deploy.sh
```

- No fim, `deploy.sh` imprime a URL e a revisão. Mensagens
  `Regional Access Boundary ... Gaia id not found for email suporte@materlux.com.br`
  são **avisos não-fatais** de uma política da organização — o deploy conclui normalmente.
- Migrações de banco: rodar o `.sql` no **Cloud SQL Studio** (banco `materlux`, usuário
  `postgres`) **antes** de publicar código que dependa de colunas novas. Ver `migrations/`.

---

## Esquema do banco (o que você precisa saber)

Schemas: `medical`, `patients`, `conversations` (entre outros).

- **Profissionais** (`medical.professionals`): Murilo = **id 1**, Isadora = **id 4**.
- **`medical.professional_schedules.day_of_week`** usa o **DOW do Postgres** (Domingo = 0).
- **`medical.appointment_statuses`:** 1=`pending_payment`, 2=`confirmed`,
  3=`cancelled_by_patient`, 4=`cancelled_by_clinic`, 5=`expired`, 6=`attended`, 7=`no_show`.
- **`medical.services.service_type_id`:** 1=consulta, 3=ultrassom, 4=retorno.
- **`medical.appointments`:** `professional_id`, `patient_id`, `service_id`, `status_id`,
  `start_time`, `end_time`, `origem` (`whatsapp` | `secretaria` | `cloud`=dados antigos
  restaurados), os campos financeiros da v2: `valor_pago numeric(10,2)`,
  `forma_pagamento varchar(20)`, `observacoes text`, e `motivo_cancelamento text`
  (migração 003 — obrigatório ao cancelar, painel e agente).
- **`patients.records`:** `first_name`, `last_name`, `email`, `cpf` (constraint única
  `records_cpf_key`, 11 dígitos), `birth_date` (v2), campos `address_*`.
- **Telefone** fica em **`patients.contacts.phone_number`** (não há unique — um telefone
  pode estar em vários cadastros).

### IDs de serviço do Dr. Murilo (úteis para testes)
1 Consulta Pré-Natal · 2 Pré-Natal On · 3 Cons. Infertilidade · 4 Infertilidade On ·
5 Cons. Ginecológica · 6 Ginecológica On · 7 US Seriada · 8 US Seriada On ·
9 US Obstétrica · 10 US Obstétrica On · 11 Inserção de Implanon · 12 Retorno · 13 Retorno On.

---

## Regras de negócio e convenções (gotchas)

- **psycopg 3:** para "não está nesta lista" use **`coluna <> ALL(%s)`** com uma **lista**
  Python — **não** use `NOT IN %s` (dá SyntaxError de placeholder).
- **Slots livres:** `_FREE_STATUS = (3, 4, 5)` — cancelados/expirados **não** ocupam a
  agenda. Por isso um agendamento cancelado (status 4) libera o horário.
- **Slots variáveis** (`app/scheduling.py`, função `slot_rule(professional_id, service_id)`):
  - Isadora (prof 4): **60 min, de hora em hora** (`:00`), nos dias da grade dela.
  - Murilo **consulta** (service_type 1): **45 min em `:00`**, 08:00–18:00.
  - Murilo **procedimento** (US/retorno/Implanon): **15 min em `:45`**, 08:45–18:45.
  - Consulta (`:00`) e procedimento (`:45`) **podem coexistir na mesma hora** do Murilo.
  - `available_slots`, `slot_minutes`, `next_available_days` recebem `service_id`.
  - Time-offs em `medical.*` usam colunas `start_timestamp`/`end_timestamp`.
- **Agente WhatsApp — casamento de paciente** (`_get_or_create_patient` em `app/agent.py`):
  reusa cadastro existente **só quando o telefone E o nome batem**; senão cria cadastro novo
  vinculado ao mesmo telefone (mãe/filho, número compartilhado). Isso corrige o bug em que
  uma reserva caía na ficha de outra paciente só porque o número coincidia.
- **Política de conversa do agente:** `app/politica_atendente.md` (versionado). O agente lê
  esse arquivo em `_load_policy`; dá pra sobrescrever via env `WA_SYSTEM_PROMPT`. Regras:
  atendimento acolhedor/objetivo, particular vs. planos, NF, encaminhar a humano só o número
  `27999949612` (ligações 8–17h), emergência SAMU 192. **Sem** QR Code / porta (desativado).

---

## Endpoints principais

- `POST /login`, `POST /logout` · `GET /app` (SPA).
- `GET /health` (rápido: banco) · `GET /health/deep` (banco + conexão Z-API +
  config Gemini; devolve **503** em falha — é o alvo do Uptime Check do Cloud
  Monitoring, a cada 5 min com alerta por e-mail). Checklist humano diário em
  `CHECKLIST-ABERTURA.md`.
- `GET /api/slots?professional_id=&service_id=&data=YYYY-MM-DD` → `{duracao_min, horarios[]}`.
- `GET /api/appointments?professional_id=&data=` → agenda (inclui campos financeiros).
- `POST /api/appointments` (cria; reusa paciente por CPF com `ON CONFLICT`).
- `GET/PUT /api/appointments/{id}` (remarcar, revalida slot) · `POST /{id}/cancel`
  (status 4) · `PATCH /{id}/financeiro`.
- `GET /api/patients/search?name=` · `POST /api/patients` (cadastro completo + ViaCEP no
  front) · `GET /api/patients/{id}/appointments` (histórico).
- `GET /api/reports/revenue?inicio=YYYY-MM-DD&fim=YYYY-MM-DD` → total por profissional +
  `total_geral` (só total geral, por decisão do cliente). Inclui **partos** (pela
  `data_pagamento`), exceto quando filtrado por forma de pagamento (partos não têm forma).
- **Partos** (`medical.partos`, migração 005): `POST/GET/PATCH/DELETE /api/partos` —
  registro com paciente, profissional, `valor_pago`, `data_pagamento`, `observacoes`.
  Aba própria no painel; partos sem `data_pagamento` aparecem em qualquer período.
- `POST /tasks/lembretes` (**Cloud Scheduler**, protegido por header
  `X-Tasks-Token` = env `TASKS_TOKEN`; sem a env, responde 503): envia o lembrete
  da véspera via `send_reply` (Z-API) para consultas de amanhã com status ativo
  (1,2) e `lembrete_enviado_em` nulo; marca a coluna ao enviar (idempotente).
  Job diário sugerido às 18:00 America/Sao_Paulo. Telefone é normalizado para
  DDI 55. **Novo secret a injetar no Cloud Run:** `TASKS_TOKEN`.
- `POST /webhook/whatsapp` (Z-API). **Transbordo humano:** se
  `conversations.sessions.atendimento_status = 'humano'`, o webhook NÃO chama o
  Gemini (silêncio; só grava a mensagem no histórico). Controle no painel (aba
  WhatsApp): `GET /api/wa/conversas` e `POST /api/wa/conversas/{phone}/status`
  (`bot`|`humano`). O bot pode se pausar via ferramenta `transferir_para_humano`;
  devolução automática ao bot após 12h (`_HANDOFF_HOURS` em `app/agent.py`).

Frontend `app/templates/app.html` tem 10 abas: Agenda, Novo agendamento, Cadastro,
Histórico, Editar agendamentos, Cancelamentos, WhatsApp (transbordo), Partos,
Prontuário, Relatórios. (A aba "Atendente virtual" de teste foi removida na v2.)

---

## Estado atual e pendências

**Publicado:** v2 completa (`3e99e1a`) + melhorias pós-v2 até o commit `bd3d5f5`:
datas em dd/mm/aaaa no frontend (campos com máscara; conversão `brToIso`/`isoToBr`),
CEP com máscara e busca automática de endereço (ViaCEP), agente WhatsApp exige/valida/
grava CPF antes de agendar, aviso em tempo real de paciente duplicada no Cadastro
(nome/CPF), editar/excluir cadastro de paciente (`GET/PUT/DELETE /api/patients/{id}`)
e validação de CPF com dígitos verificadores unificada em `app/validators.py`
(usada pelo agente e pelo `POST`/`PUT` de pacientes).

**Regras novas que valem lembrar:**
- Exclusão de paciente é **bloqueada** (409) se houver agendamentos ou evoluções
  clínicas na ficha — nesses casos o caminho é editar (ou Cloud SQL Studio).
- No `PUT /api/patients/{id}` só **nome e CPF válido** são obrigatórios (cadastros
  antigos restaurados não têm e-mail/nascimento/endereço); no `POST` todos os campos
  continuam obrigatórios.

**Pendências (limpeza de dados de teste, quando o usuário fizer):**
1. Cadastros duplicados da Suhelen: `patients.records` ids **158** e **290** (mesmo
   telefone `5527998833450`) — dá para resolver pela própria aba Cadastro (buscar →
   excluir a ficha sem agendamentos); se ambas tiverem histórico, Cloud SQL Studio.
2. Ficha "Daniele Scherrer" (id **183**) com CPF **08554809718** vinculado
   incorretamente — corrigir pela edição na aba Cadastro. A ficha não pode ser
   excluída: tem o agendamento de teste `medical.appointments` id **652**
   (10/07 09:30, WhatsApp, status 4, número `5527988838365`).

---

## Layout do repositório

```
app/
  main.py             # app FastAPI, rotas base, webhook
  config.py           # Settings via env (sem segredos no código)
  db.py               # pool psycopg3 + helper db.query(...)
  security.py         # login, JWT cookie, current_user, papéis
  scheduling.py       # slots variáveis por profissional/serviço
  agent.py            # atendente Gemini (tool-calling) + Z-API
  politica_atendente.md  # regras de conversa do agente (versionado)
  templates/app.html  # SPA (7 abas)
  routers/
    appointments.py   # agenda, criar/editar/cancelar, financeiro, relatórios
    patients.py       # busca, cadastro, histórico
    partos.py         # registro de partos (valor/data de pagamento → relatórios)
    tasks.py          # tarefas do Cloud Scheduler (lembrete de 24h via Z-API)
migrations/           # 001..006 (005 = partos; 006 = lembrete_enviado_em)
deploy.sh             # crane push + gcloud run deploy
REQUISITOS-V2.md      # especificação da v2
V2-STATUS.md          # checklist de publicação da v2
```
