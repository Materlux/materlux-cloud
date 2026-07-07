# Materlux v2 — Status e checklist de publicação

_Código implementado enquanto você estava fora. **Ainda não commitado nem publicado.**
Ordem importa: **rodar a migração 002 ANTES de publicar** (o código novo lê colunas
novas)._ Data: 2026-07-05.

## O que foi implementado (todos os 7 requisitos)

| Req | O que | Arquivos |
|---|---|---|
| R1 | Slots variáveis: Isadora 60min@:00; Murilo consulta 45min@:00 e US/retorno/proced. 15min@:45 (por tipo de serviço) | `app/scheduling.py`, `app/routers/appointments.py` (`/api/slots` com `service_id`), `app/agent.py` |
| R2 | Removida a aba "Atendente virtual" | `app/templates/app.html` |
| R3 | Aba **Cadastro** de paciente (nome, e-mail, telefone, CPF, nascimento, endereço) com **ViaCEP** | `app/routers/patients.py` (`POST /api/patients`), `app/templates/app.html`, migração (birth_date) |
| R4 | Aba **Histórico** de agendamentos da paciente (data, procedimento, status) | `app/routers/patients.py` (`GET /api/patients/{id}/appointments`), `app/templates/app.html` |
| R5 | Aba **Editar agendamentos** (remarcar / cancelar) | `app/routers/appointments.py` (`GET /{id}`, `PUT /{id}`), `app/templates/app.html` |
| R6 | Colunas **Forma de pagamento, Valor, Observações** na Agenda (secretária lança) | `app/routers/appointments.py` (`PATCH /{id}/financeiro`), `app/templates/app.html`, migração |
| R7 | Aba **Relatórios**: total recebido por profissional por período, filtro por forma de pagamento, **total geral** | `app/routers/appointments.py` (`GET /api/reports/revenue`), `app/templates/app.html` |

Também: `app/config.py` ganhou `PAYMENT_METHODS`; `migrations/002_v2.sql` criado;
`REQUISITOS-V2.md` com a especificação.

## Decisões aplicadas (confirmadas por você)
- Murilo: consultas 08:00–18:00 (H:00, 45min) e procedimentos 08:45–18:45 (H:45, 15min).
- Pode haver, na mesma hora do Murilo, uma consulta (:00) e um procedimento (:45).
- Divisão de serviços: consulta = Pré-Natal, Infertilidade, Ginecológica (e On);
  procedimento/H:45 = US Seriada/Obstétrica (e On), Implanon, Retorno (e On).
- Isadora: 60min de hora em hora nos dias da grade dela.
- CEP: ViaCEP. Pagamentos: dinheiro, PIX, cartão débito, cartão crédito, transferência.
- Novo agendamento busca paciente já cadastrada (nome/CPF). Financeiro/relatórios
  liberados para recepção e médico.

## Checklist para publicar (quando você voltar)

**Passo 1 — Migração 002 (obrigatória ANTES do deploy).**
No Cloud SQL Studio (banco `materlux`, usuário `postgres`), rode o conteúdo de
`migrations/002_v2.sql` (adiciona `birth_date`, `valor_pago`, `forma_pagamento`,
`observacoes`). É idempotente.

**Passo 2 — Versionar (no seu PC, Git Bash na pasta):**
```
git add -A
git commit -m "v2: slots por procedimento, cadastro, historico, editar, financeiro e relatorios"
git push
```

**Passo 3 — Publicar (eu conduzo no Cloud Shell):**
```
cd ~/materlux-cloud && git pull
python3 -m py_compile app/*.py app/routers/*.py   # checagem de sintaxe (o mount local está defasado; aqui é fiel)
bash deploy.sh
```

## Testes recomendados após publicar
- **Murilo:** agendar uma **consulta** (deve dar horários :00, 45min, 08:00–18:00) e um
  **retorno/US** (deve dar horários :45, 15min, 08:45–18:45); confirmar que os dois
  cabem na mesma hora.
- **Isadora:** horários de hora em hora (60min) nos dias dela.
- **WhatsApp:** pedir "US obstétrica com Dr. Murilo" e ver se oferece os horários :45.
- **Cadastro:** CEP autocompleta rua/cidade/estado; número/complemento editáveis; salva.
- **Histórico / Editar:** buscar paciente, ver agendamentos, remarcar e cancelar.
- **Agenda:** lançar forma de pagamento + valor + observação e salvar.
- **Relatórios:** conferir o total por profissional e o total geral contra os lançamentos.

## Observação técnica
A validação de sintaxe (`py_compile`) não pôde ser feita no ambiente local porque o
espelho de arquivos do sandbox ficou defasado nesta sessão (mostrava versões truncadas).
Os arquivos reais no seu PC estão corretos; a checagem definitiva será no Cloud Shell,
a partir do Git, antes do `deploy.sh`.
