# Versionamento e deploy — Materlux

## Duas camadas de versão

1. **Código-fonte:** Git, no repositório **privado** `Materlux/materlux-cloud` (GitHub).
   Toda mudança é um commit — histórico de o que mudou, quando e por quê.
2. **Aplicação no ar:** cada deploy cria uma **revisão imutável** no Cloud Run
   (`materlux-api-00001`, `-00002`, ...). A imagem é marcada com o **commit do Git**,
   então cada revisão aponta para um ponto exato do código.

## Fazer uma alteração e publicar

No seu PC (Windows), na pasta `materlux-cloud`:

```
git add -A
git commit -m "descreva a mudança"
git push
```

Depois, no **Cloud Shell** (onde ficam gcloud/docker/crane), com o repositório clonado:

```
cd materlux-cloud
git pull
bash deploy.sh
```

O `deploy.sh` marca a imagem com o commit atual, publica no Artifact Registry
(via crane) e implanta no Cloud Run.

## Voltar uma versão (rollback)

Listar revisões e mandar 100% do tráfego para uma anterior:

```
gcloud run revisions list --service materlux-api --region southamerica-east1
gcloud run services update-traffic materlux-api --region southamerica-east1 \
    --to-revisions <REVISAO-ANTERIOR>=100
```

Nenhum rebuild é preciso para reverter — as revisões antigas continuam guardadas.

## Nunca versionar

Segredos e dumps ficam de fora (ver `.gitignore`): `.env`, `*.sql`, `*.dump`,
chaves de service account. As credenciais reais vivem no **Secret Manager**.

## Primeiro envio (uma vez só)

Ver o passo a passo no chat / no README. Resumo: criar o repositório privado
`materlux-cloud` no GitHub e, na pasta, rodar `git init` → `add` → `commit` →
`remote add origin` → `push -u origin main`.
