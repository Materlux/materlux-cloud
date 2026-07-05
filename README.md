# Materlux Cloud

Sistema de agenda + prontuário + atendente virtual de WhatsApp, **100% na nuvem**
(sem servidor físico), acessível de qualquer navegador. Um único serviço FastAPI
substitui o antigo trio *n8n (519 nós) + Streamlit + API Node*.

- **Plano, arquitetura e custos:** `ARQUITETURA-E-PLANO.md`
- **Documento de operação/contingência:** `OPERACAO.md`

## Estrutura

```
app/
  main.py            App FastAPI (UI + API + webhook)
  config.py          Configuração por variáveis de ambiente
  db.py              Pool Postgres com TLS
  security.py        Login: bcrypt + JWT em cookie httpOnly
  scheduling.py      Cálculo de horários livres (UI e agente usam o mesmo)
  agent.py           Atendente virtual (Gemini com tool-calling)
  routers/           auth, appointments, patients, evolutions, whatsapp
  templates/         login.html, app.html
migrations/001_...   Schema novo (usuários, evoluções, campos de origem)
seed_users.py        Define senhas com hash
backup_to_gcs.py     Backup diário + alerta se falhar
render.yaml          Deploy (web + cron de backup)
```

## Subir em produção (resumo — detalhes em OPERACAO.md)

1. **Banco:** crie um Postgres gerenciado (Supabase ou Neon). Copie a `DATABASE_URL`.
2. **Restaure o dump** da clínica nesse banco (cópia — nunca o original):
   ```
   psql "$DATABASE_URL" -f database/materlux_2026-04-23_02-00.sql
   ```
3. **Aplique a migração** do schema novo:
   ```
   psql "$DATABASE_URL" -f migrations/001_auth_evolutions_origin.sql
   ```
4. **Configure o `.env`** a partir de `.env.example`.
5. **Defina as senhas** da equipe:
   ```
   python seed_users.py murilo   SuaSenhaForte
   python seed_users.py isadora  SuaSenhaForte
   python seed_users.py recepcao SuaSenhaForte
   ```
6. **Rode local** para testar:
   ```
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
   Acesse http://localhost:8000 → login → Agenda / Prontuário / Atendente virtual.
7. **Deploy:** conecte o repositório ao Render (`render.yaml`) ou Railway/Cloud Run.

## WhatsApp

O webhook `/webhook/whatsapp` é agnóstico de provedor (`WA_PROVIDER = zapi | meta | console`).
Aponte o provedor escolhido para `https://SEU-APP/webhook/whatsapp`.
A aba **Atendente virtual** simula a conversa sem enviar WhatsApp real (`WA_PROVIDER=console`).

## Segurança / LGPD

Sem senhas ou tokens no código (tudo em variáveis de ambiente). Conexão ao banco por
TLS. Cookies `httpOnly`/`secure`. Prontuários acessíveis só após login; inserção de
evolução restrita ao perfil `medico`.
