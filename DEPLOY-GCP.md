# Deploy no Google Cloud (Cloud SQL + Cloud Run + Z-API)

Escolhas: banco **Cloud SQL (PostgreSQL)**, app em **Cloud Run**, WhatsApp por **Z-API**.
Fica tudo no mesmo GCP dos backups. O dump de 23/04 já está no bucket, então o
Cloud SQL importa direto de lá.

## 1. Criar o banco (Cloud SQL PostgreSQL)

Console → SQL → *Create instance* → PostgreSQL 15+.
- Edition: **Enterprise**, preset **Sandbox** ou **Lightweight** (menor custo, ~US$10-15/mês).
- Região: `southamerica-east1` (São Paulo) — menor latência e dado no Brasil (LGPD).
- **Defina a senha do usuário `postgres`** — *isto é você quem faz* (nunca por mim).
- Storage: 10 GB SSD, com *automatic increase* ligado.
- Backups automáticos: **ligados** (além do nosso `backup_to_gcs.py`).
- Marque *Require SSL/TLS*.

Depois: crie um database chamado `materlux` (aba *Databases* → *Create database*).

## 2. Restaurar o dump de 23/04 (import do GCS)

Console → sua instância → *Import*:
- Source: `gs://postgres-materlux-backups/database/materlux_2026-04-23_02-00.sql`
- Format: **SQL** · Database: `materlux`

> Dá à conta de serviço do Cloud SQL permissão de leitura no bucket, se pedir.
> O import é sobre um banco novo — **não** toca no backup original.

## 3. Aplicar a migração do schema novo

Console → instância → *Cloud SQL Studio* (ou `psql`), banco `materlux`, cole o conteúdo de
`migrations/001_auth_evolutions_origin.sql` e execute.

## 4. Montar a DATABASE_URL

```
postgresql://postgres:SUA_SENHA@/materlux?host=/cloudsql/PROJETO:REGIAO:INSTANCIA
```
No Cloud Run use o socket `/cloudsql/...` (adicione a conexão Cloud SQL ao serviço).
Para rodar/testar de fora, use a **IP pública** da instância + `sslmode=require`:
```
postgresql://postgres:SUA_SENHA@IP_PUBLICO:5432/materlux
```

## 5. Definir as senhas da equipe

```
export DATABASE_URL="...(passo 4)..."
pip install -r requirements.txt
python seed_users.py murilo   SuaSenhaForte
python seed_users.py isadora  SuaSenhaForte
python seed_users.py recepcao SuaSenhaForte
```

## 6. Deploy do app no Cloud Run

```
gcloud run deploy materlux-api \
  --source . --region southamerica-east1 --allow-unauthenticated \
  --add-cloudsql-instances PROJETO:REGIAO:INSTANCIA \
  --set-env-vars "DATABASE_URL=...,JWT_SECRET=...,GEMINI_API_KEY=...,WA_PROVIDER=zapi,\
WA_VERIFY_TOKEN=materlux-verify,ZAPI_INSTANCE=...,ZAPI_TOKEN=...,ZAPI_CLIENT_TOKEN=..."
```
Guarde os segredos preferencialmente no **Secret Manager** e referencie com
`--set-secrets` em vez de `--set-env-vars`.

## 7. Conectar o Z-API

1. No painel Z-API, crie a instância e conecte seu número por QR Code.
2. Em *Webhooks → Ao receber*, aponte para: `https://SEU-CLOUD-RUN/webhook/whatsapp`.
3. Copie `Instance ID`, `Token` e `Client-Token` para as variáveis `ZAPI_*`.

## 8. Backup diário (Cloud Scheduler + Cloud Run Job)

Rode `backup_to_gcs.py` 1x/dia. Configure `BACKUP_ALERT_WEBHOOK` para receber alerta
(ex.: um endpoint do próprio Z-API para o seu WhatsApp) caso o backup falhe — foi a
ausência disso que causou a perda silenciosa em 23/04.

## O que preciso de você

- **DATABASE_URL** (após criar a instância e definir a senha do `postgres`).
- **GEMINI_API_KEY**.
- **ZAPI_INSTANCE / ZAPI_TOKEN / ZAPI_CLIENT_TOKEN**.

Com isso eu faço a migração, o seed, o deploy e rodo os testes ponta a ponta antes de
você chamar as pacientes.
