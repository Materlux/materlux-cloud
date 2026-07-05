"""Backup automático do Postgres para o Google Cloud Storage, com ALERTA se falhar.

Resolve a causa da contingência: os backups antigos pararam em 23/04 sem ninguém
notar. Aqui, qualquer falha dispara um alerta (webhook) e sai com código != 0,
para que o agendador (cron do Render / Cloud Scheduler) marque a execução como falha.

Uso:  python backup_to_gcs.py
Requer: pg_dump no PATH, DATABASE_URL, GCS_BUCKET, GOOGLE_APPLICATION_CREDENTIALS.
"""
import os
import sys
import subprocess
import datetime
import tempfile
import httpx
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
BUCKET = os.getenv("GCS_BUCKET", "postgres-materlux-backups")
ALERT = os.getenv("BACKUP_ALERT_WEBHOOK", "")


def alert(msg: str):
    print("ALERTA:", msg)
    if ALERT:
        try:
            httpx.post(ALERT, json={"text": f"[Materlux backup] {msg}"}, timeout=10)
        except Exception as e:  # noqa
            print("Falha ao enviar alerta:", e)


def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    fname = f"materlux_{stamp}.sql"
    tmp = os.path.join(tempfile.gettempdir(), fname)
    try:
        with open(tmp, "wb") as f:
            subprocess.run(["pg_dump", "--no-owner", "--no-privileges", DATABASE_URL],
                           check=True, stdout=f)
        if os.path.getsize(tmp) < 10_000:
            raise RuntimeError("Dump suspeito: arquivo muito pequeno.")

        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(BUCKET).blob(f"database/{fname}")
        blob.upload_from_filename(tmp)
        print(f"OK: gs://{BUCKET}/database/{fname} ({os.path.getsize(tmp)} bytes)")
    except Exception as e:  # noqa
        alert(f"BACKUP FALHOU em {stamp}: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    main()
