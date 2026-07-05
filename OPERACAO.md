# Materlux — Operação e Contingência

Guia curto: como acessar, como restaurar um backup, onde ficam as credenciais e o
que fazer em nova contingência.

## Como acessar o sistema

- Endereço: `https://SEU-APP` (definido no deploy do Render/Railway).
- Logins (senhas definidas com `seed_users.py`):
  - `murilo` / `isadora` — perfil **médico** (agenda + prontuário + evoluções).
  - `recepcao` — perfil **secretária** (agenda + agendamentos; sem inserir evolução).

## Onde ficam as credenciais

Nenhuma credencial no código. Tudo em variáveis de ambiente do serviço (Render →
*Environment*) e no `.env` local (não versionado). Segredos usados:
`DATABASE_URL`, `JWT_SECRET`, `GEMINI_API_KEY`, tokens do WhatsApp, credencial do GCS.

## Backups

- Rotina diária (`backup_to_gcs.py`) faz `pg_dump` e envia para
  `gs://postgres-materlux-backups/database/`.
- **Alerta de falha:** se o backup falhar, dispara `BACKUP_ALERT_WEBHOOK` e a
  execução termina com erro (aparece como *failed* no painel). Foi exatamente a
  falta disso que causou a perda silenciosa em 23/04/2026.
- **Confira 1x/semana** que o backup mais recente existe no bucket.

## Restaurar um backup

Sempre em uma cópia/banco novo — nunca por cima do banco em uso sem confirmação:

```
# 1. baixe o dump desejado do GCS
gsutil cp gs://postgres-materlux-backups/database/materlux_AAAA-MM-DD_HH-MM.sql .

# 2. restaure em um banco limpo
psql "$DATABASE_URL_NOVO" -f materlux_AAAA-MM-DD_HH-MM.sql

# 3. reaplique a migração do schema novo
psql "$DATABASE_URL_NOVO" -f migrations/001_auth_evolutions_origin.sql
```

## Nova contingência (passo a passo)

1. O app caiu? Verifique `GET /health` — mostra se o banco está acessível.
2. Banco indisponível? O provedor (Supabase/Neon) tem painel de status e restauração
   *point-in-time*. Se necessário, crie um banco novo e restaure o último dump do GCS.
3. Reaponte `DATABASE_URL` no serviço e reinicie. Sem servidor físico envolvido.

## Fase 1.5 — reimportar o período perdido (24/04 → hoje)

Quando o SSD antigo for recuperado, os registros de 24/04 em diante serão mesclados
sem duplicar: cada agendamento/evolução tem `origem` e `id_legado`. O procedimento
será: importar marcando `origem='ssd_recuperado'` e resolver conflitos por
(`professional_id`, `start_time`) nos agendamentos.

## Reconstituir a agenda perdida por fontes secundárias

Enquanto o SSD não volta, a agenda de 24/04→hoje pode ser reconstruída a partir do
histórico do WhatsApp Business (cada agendamento antigo virou mensagem) e das anotações
da secretária. Reinsira pela aba **Novo agendamento** — esses registros ficam com
`origem='secretaria'`; se quiser distingui-los, podemos marcar `reconstituido`.
