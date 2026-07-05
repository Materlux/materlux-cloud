# Materlux na nuvem — Plano de reconstrução (refatorado)

_Documento de decisão. Data: 2026-07-04._

## 1. O que muda em relação ao sistema antigo

| Antes (servidor físico) | Agora (nuvem) |
|---|---|
| PostgreSQL no mini PC (SSD queimou) | **Postgres gerenciado** (Supabase / Neon) — TLS, criptografia em repouso, backup automático |
| n8n com **519 nós** orquestrando o WhatsApp | **Agente enxuto em Python** (Gemini com _tool-calling_) — ~1 arquivo, mesma função |
| Frontend Streamlit local da secretária | **App web único com login** (médico e secretária), acessível de qualquer navegador |
| API Node no PC + backend Python separado | **Um único serviço FastAPI** faz UI + API + webhook do WhatsApp |
| Sem login / senha "1234" no código | **Login real** com senha com hash (bcrypt) e sessão via JWT |
| Backups que pararam em 23/04 sem ninguém notar | **Backup automático + alerta** se a rotina falhar |

Tudo roda na nuvem. **Nenhuma dependência de servidor físico.**

## 2. Arquitetura proposta

```
                    ┌─────────────────────────────────────────┐
   Paciente         │            materlux-api (FastAPI)        │
   (WhatsApp) ─────▶│  /webhook/whatsapp ─▶ Agente (Gemini)    │
                    │                         │ tool-calling   │
   Provedor WA      │                         ▼                │
   (Z-API/Meta)     │   scheduling.py  ◀──────┤                │
                    │   (horários livres)     │                │
                    │                         ▼                │
   Médico   ───────▶│  /login ─▶ /app ─▶ Agenda + Prontuário   │──▶ Postgres
   Secretária       │            (JWT em cookie httpOnly)      │   gerenciado
                    └─────────────────────────────────────────┘        │
                                                                        ▼
                                                        Backup automático → GCS
                                                        (+ alerta se falhar)
```

Um só serviço, um só banco. A secretária grava agendamentos no **mesmo banco** que o agente do WhatsApp — exatamente como antes.

## 3. Stack escolhida e justificativa

**Banco: Supabase (Postgres gerenciado).**
Recomendado para começar: tem plano gratuito para testes, sobe em minutos, dá TLS e criptografia em repouso por padrão, faz backup diário e restaura o dump PostgreSQL sem conversão. Alternativa equivalente: **Neon** (também Postgres puro). Ambos servem; a decisão prática é custo/simplicidade — ver seção 5.

**Aplicação: FastAPI (Python).** Mantém o ecossistema que você já usa (o backend antigo já era FastAPI + Gemini), consolida tudo em um serviço e serve tanto a UI quanto o webhook. Hospedagem em **Render** ou **Railway** (deploy por git, HTTPS automático, sem servidor para administrar). Se preferir ficar 100% no Google Cloud — que você já usa para os backups — dá para hospedar em **Cloud Run** com o mesmo código.

**Frontend: página web única servida pelo próprio FastAPI** (HTML + JS leve). Substitui o Streamlit, que não foi feito para múltiplos usuários com login nem exposição pública. Mais rápido, mais seguro e sem processo separado.

## 4. WhatsApp: recomendação sobre a API da Meta

A **WhatsApp Cloud API oficial da Meta** funciona, mas para colocar no ar rápido ela tem atrito: verificação do Facebook Business, aprovação de _templates_ de mensagem, número dedicado. Para **testes reais com pacientes agora**, recomendo:

- **Opção A (mais rápida) — Z-API** (provedor brasileiro): REST + webhook simples, conecta o número por QR Code, sem verificação da Meta. ~R$ 99/mês. Ideal para os testes iniciais.
- **Opção B (grátis, self-host) — Evolution API**: open-source, mesma ideia de conectar por QR. Custo só de hospedagem. O código antigo já mencionava Evolution/Z-API, então o formato do webhook já é compatível.
- **Opção C (oficial, futuro) — Meta Cloud API**: melhor para escala e conformidade a longo prazo. Vale migrar depois que o fluxo estiver validado.

O código foi escrito **agnóstico de provedor**: o webhook recebe `{telefone, mensagem}` e responde texto. Trocar Z-API ↔ Meta é mudar só o adaptador de envio, não o agente.

## 5. Custo mensal estimado (clínica pequena)

| Item | Opção de teste | Opção produção |
|---|---|---|
| Banco Postgres | Supabase Free (R$ 0) | Supabase Pro ~US$ 25 |
| Hospedagem do app | Render Free / Railway ~US$ 5 | Render Starter ~US$ 7 |
| WhatsApp | Evolution self-host (~US$ 5) ou Z-API R$ 99 | Z-API R$ 99 ou Meta (por conversa) |
| Gemini (agente) | Free tier | ~US$ 5–15 conforme volume |
| Backups no GCS | Centavos | Centavos |
| **Total aprox.** | **~R$ 100–150/mês** | **~R$ 300–400/mês** |

Nada é provisionado sem sua aprovação. Os valores pagos começam só quando você autorizar.

## 6. Fases

- **Fase 1 (agora):** banco na nuvem + app web com login (agenda das duas partes + prontuário) + **agente do WhatsApp agendando de verdade**. Restante do fluxo antigo fica manual com a secretária.
- **Fase 1.5:** reimportar o período perdido (24/04→hoje) quando o SSD for recuperado — o novo esquema já marca `origem` e `id_legado` em cada registro para mesclar sem duplicar.
- **Fase 2:** reintroduzir QR Code + porta Intelbras, lembretes, pagamento, e migrar para a Meta API oficial se desejado.

## 7. O que preciso de você para colocar no ar

1. **String de conexão do Postgres** gerenciado (você cria a conta Supabase/Neon e me passa a `DATABASE_URL`).
2. **Chave da API do Gemini** (`GEMINI_API_KEY`).
3. **Credenciais do provedor de WhatsApp** escolhido (token Z-API ou dados da Meta).
4. Autorização para o **deploy** em Render/Railway/Cloud Run (a conta é sua; o código já está pronto).

Enquanto isso, o código, o esquema e o guia de operação já estão prontos neste pacote.
