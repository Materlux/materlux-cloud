# Checklist de abertura — Materlux Cloud (≈2 minutos)

Fazer **todo dia ao abrir a clínica**, antes do primeiro atendimento.

1. [ ] Abrir o painel (`https://materlux-api-737153954505.southamerica-east1.run.app/app`)
       e fazer login normalmente.
2. [ ] **Aba Agenda:** a agenda de hoje carrega e mostra os agendamentos esperados.
3. [ ] **Aba WhatsApp:** conferir se ficou algum contato "⏸ com humano" esquecido de
       ontem — se sim, clicar em **Devolver para o bot**.
4. [ ] Do **celular de teste**, mandar "oi" para o WhatsApp da clínica →
       a atendente virtual deve responder em até ~1 minuto.
5. [ ] Se qualquer item falhar: abrir
       `https://materlux-api-737153954505.southamerica-east1.run.app/health/deep`
       no navegador — a resposta mostra o que está fora (`db`, `whatsapp` ou
       `gemini`) — e avisar o Dr. Murilo.

Problemas mais comuns e primeiro socorro:

- **`whatsapp: desconectado`** → o celular da clínica perdeu o pareamento com a
  Z-API. Reconectar no painel da Z-API (ler o QR Code com o WhatsApp do celular
  da clínica).
- **`db: erro`** → problema no banco/Cloud SQL. Avisar o Dr. Murilo (console do
  Google Cloud, projeto `mata-da-praia-workflows`).
- **Painel não abre** → verificar o Cloud Run (serviço `materlux-api`) no console.

> O sistema também é vigiado automaticamente pelo Cloud Monitoring (Uptime Check
> no `/health/deep` a cada 5 minutos, com alerta por e-mail). Este checklist é a
> camada humana: pega o que o robô não vê.
