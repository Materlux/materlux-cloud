# Materlux — Requisitos da versão 2

_Especificação para revisão. Serve também como "contexto quente" caso a gente
continue em outra tarefa. Data: 2026-07-05._

## 1. Contexto atual (o que já está no ar)

- **App:** https://materlux-api-737153954505.southamerica-east1.run.app (Cloud Run,
  projeto `mata-da-praia-workflows`, região `southamerica-east1`).
- **Banco:** Cloud SQL PostgreSQL `materlux-db` (banco `materlux`), backup diário 03:00 BRT.
- **Profissionais (bookáveis):** Dr. Murilo Ferraz = **id 1**; Dra. Isadora Vencioneck = **id 4**.
- **Grade (medical.professional_schedules), dow no padrão Postgres (dom=0):**
  - Murilo: seg(1), qua(3), sex(5) — 08:00–19:00.
  - Isadora: ter(2) 14:00–18:00; qua(3) 08:00–13:00; qui(4) 13:00–18:00.
- **Serviços (medical.services) por profissional (medical.professional_services):**
  - Murilo (1): 1 Pré-Natal, 2 Pré-Natal On, 3 Infertilidade, 4 Infertilidade On,
    5 Ginecológica, 6 Ginecológica On, 7 US Seriada, 8 US Seriada On, 9 US Obstétrica,
    10 US Obstétrica On, 11 Inserção de Implanon, 12 Retorno, 13 Retorno On.
  - Isadora (4): 14 Pediátrica, 15 Pediátrica On, 16 Pré-Natal Pediátrico,
    17 Pré-Natal Pediátrico On, 18 Consulta + Bochechinha, 12 Retorno, 13 Retorno On.
  - `service_type_id`: **1 = consulta**, **3 = ultrassom/procedimento**, **4 = retorno**.
- **Deploy:** editar → `git commit`/`push` (PC) → no Cloud Shell `git pull` + `bash deploy.sh`
  (imagem marcada pelo commit, publicada via crane, implantada no Cloud Run).
- **Stack do app:** FastAPI (`app/`), UI em `templates/app.html`, agente WhatsApp em
  `app/agent.py` (Gemini + tool-calling), política em `app/politica_atendente.md`.

## 2. Decisões confirmadas

- **Slots do Dr. Murilo por tipo de serviço** (confirmado):
  - **Consulta** (service_type 1: Pré-Natal, Infertilidade, Ginecológica e versões On)
    → slot de **45 min**, ancorado na **hora cheia (H:00)**.
  - **Procedimento/US/Retorno** (service_type 3 e 4: US Seriada/Obstétrica e On,
    Implanon, Retorno e On) → slot de **15 min**, ancorado em **H:45**.
- **Dra. Isadora:** todo serviço → slot de **60 min**, de **hora em hora (H:00)**,
  nos dias/faixas da grade dela.
- **CEP:** usar **ViaCEP** (`https://viacep.com.br/ws/{cep}/json/`), gratuito, sem chave.
- **Formas de pagamento:** dinheiro, PIX, cartão débito, cartão crédito, transferência.

## 3. Requisitos detalhados

### R1 — Slots variáveis por profissional e procedimento
Regra de geração (derivada de profissional + service_type, sem precisar cadastrar
duração serviço a serviço; novos serviços herdam a regra pelo tipo):

- **Isadora (id 4):** para qualquer serviço → slots a cada 60 min, início em H:00,
  dentro de cada faixa da grade.
- **Murilo (id 1):**
  - service_type **1** (consulta) → slots em **H:00**, duração **45 min**
    (ex.: 08:00–08:45, 09:00–09:45, …).
  - service_type **3 ou 4** (US/retorno/procedimento) → slots em **H:45**, duração
    **15 min** (ex.: 08:45–09:00, 09:45–10:00, …).
- Na mesma hora, a consulta (H:00–H:45) e o procedimento (H:45–H:00) **não colidem**,
  então ambos podem existir (até 2 marcações por hora para o Murilo). A disponibilidade
  de um horário considera colisão com **qualquer** agendamento já existente (de qualquer
  tipo) e com bloqueios (professional_timeoff).
- **Alcance:** seguir a faixa da grade. Para Murilo (08:00–19:00): consultas de 08:00 a
  18:00 e procedimentos de 08:45 a 18:45. **(confirmar — ver Pontos em aberto.)**

**Onde muda:**
- `app/scheduling.py`: `available_slots(professional_id, service_id, target_date)` passa a
  gerar os slots conforme a regra acima (duração e âncora dependem de profissional + tipo
  do serviço), removendo os que colidem com agendamentos/bloqueios.
- `app/agent.py`: a ferramenta `consultar_horarios` passa a receber `service_id` e a
  oferecer os horários corretos do procedimento escolhido; `criar_agendamento` grava
  `end_time` com a duração certa. O agente conduz: escolher profissional → escolher
  serviço → oferecer horários daquele serviço.
- `app/routers/appointments.py`: `/api/slots` passa a exigir `service_id`; o
  `create_appointment` calcula a duração pela regra.
- `templates/app.html`: em "Novo agendamento", os horários são buscados **depois** de
  escolher o serviço.

### R2 — Remover a aba "Atendente virtual" (testes)
- `templates/app.html`: remover a aba e o endpoint interno `/api/simulate` (opcional
  manter o endpoint desativado). O webhook real do WhatsApp continua igual.

### R3 — Nova aba "Cadastro" de paciente
Campos **obrigatórios**: nome completo, e-mail, telefone, CPF, data de nascimento,
endereço. CEP autocompleta rua/cidade/estado (ViaCEP); **número** e **complemento**
editáveis. (Base para emissão de nota fiscal.)
- **Banco:** `patients.records` hoje tem email, cpf, first_name, last_name, address_*
  (street, neighbourhood, complement, city, state, zipcode, country, number) mas **não
  tem data de nascimento** → migração adiciona `birth_date date`. Telefone vai em
  `patients.contacts.phone_number`.
- **Backend:** `POST /api/patients` (cria com todos os campos + contato de telefone).
- **Frontend:** formulário com busca de CEP (chamada ao ViaCEP no navegador),
  validação de obrigatórios e de CPF.

### R4 — Nova aba "Histórico" de agendamentos da paciente
- Buscar paciente e listar seus agendamentos: **data, procedimento (serviço), status**.
- **Backend:** `GET /api/patients/{id}/appointments` (ordenado por data desc).
- **Frontend:** busca por nome/CPF → lista o histórico.

### R5 — Nova aba "Editar agendamentos"
- Para **remarcar** (mudar profissional/serviço/data/hora) ou **cancelar**.
- **Backend:** `GET /api/appointments/{id}`, `PUT /api/appointments/{id}` (revalida
  disponibilidade ao remarcar), `POST /api/appointments/{id}/cancel` (já existe).
- **Frontend:** localizar o agendamento (por paciente/data) → editar horário ou cancelar.

### R6 — Colunas financeiras na aba "Agenda"
Tabela passa a ter: **HORA, PACIENTE, SERVIÇO, STATUS, ORIGEM, FORMA DE PAGAMENTO,
VALOR, OBSERVAÇÕES**. A secretária lança forma de pagamento, valor pago e observações
por linha.
- **Banco:** `medical.appointments` ganha `valor_pago numeric(10,2)`,
  `forma_pagamento varchar(20)`, `observacoes text`.
- **Backend:** `PATCH /api/appointments/{id}/financeiro` (grava os três campos).
- **Frontend:** células editáveis na tabela da agenda + botão salvar por linha.

### R7 — Nova aba "Relatórios"
- Somar **valores recebidos por PROFISSIONAL** por intervalo de datas, com filtro por
  **forma de pagamento**.
- **Backend:** `GET /api/reports/revenue?start=&end=&forma_pagamento=&professional_id=`
  → soma `valor_pago` agrupada por profissional (e por forma, se útil).
- **Frontend:** intervalo de datas + filtro de forma de pagamento → tabela com total
  por profissional.

## 4. Migração de banco (migrations/002_v2.sql)

```
ALTER TABLE patients.records   ADD COLUMN IF NOT EXISTS birth_date date;
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS valor_pago numeric(10,2);
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS forma_pagamento varchar(20);
ALTER TABLE medical.appointments ADD COLUMN IF NOT EXISTS observacoes text;
```
(Aplicada no Cloud SQL Studio, como a migração 001.)

## 5. Plano em fases (cada fase = commit + deploy + teste)

1. **Fase A — Slots variáveis (R1):** o núcleo. Reescrever `scheduling.py`, ajustar
   `/api/slots`, `create_appointment`, `agent.py` (tool com service_id) e a UI de
   "Novo agendamento". Testar manual + WhatsApp para os dois profissionais e os dois
   tipos de slot do Murilo.
2. **Fase B — Migração 002 + Cadastro (R3):** nova coluna birth_date, endpoint e aba
   de cadastro com ViaCEP.
3. **Fase C — Financeiro na Agenda (R6) + Relatórios (R7):** colunas valor/forma/obs,
   edição na agenda e relatório por profissional.
4. **Fase D — Histórico (R4) + Editar agendamentos (R5) + remover aba de testes (R2).**

## 6. Pontos em aberto (preciso da sua confirmação)

1. **Alcance da agenda do Murilo:** a grade dele é 08:00–19:00. Mantenho consultas de
   **08:00 a 18:00** e procedimentos de **08:45 a 18:45**? Ou você quer travar em 17:45
   (como no exemplo que você deu)? Se a jornada real termina mais cedo, me diga o fim.
2. **Duas marcações por hora (Murilo):** confirmo que é intencional poder ter, na mesma
   hora, uma consulta (H:00) **e** um procedimento (H:45)?
3. **Relatórios:** além do total por profissional, quer também o **detalhamento** (lista
   de cada atendimento com valor/forma) no período? E o total geral somado?
4. **Cadastro x agendamento:** a aba "Cadastro" cria a paciente; no "Novo agendamento"
   você quer **buscar** a paciente já cadastrada (por nome/CPF) em vez de digitar de novo?
   (Recomendo sim — evita duplicar.)
5. **Permissões:** os relatórios financeiros e a edição de valores ficam liberados para
   **recepção e médico**, ou só para o médico? (Hoje tudo que não é evolução é liberado
   para os dois.)

## 7. Testes por fase
Manual (web) + WhatsApp (agente) para agendamento; verificação em banco das durações e
colisões; conferência dos totais de relatório contra lançamentos de teste.
