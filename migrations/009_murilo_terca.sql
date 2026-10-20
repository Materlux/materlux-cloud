-- 009: Dr. Murilo (prof 1) passa a atender TERÇAS (em vez de segundas).
-- Grade nova: ter(2), qua(3), sex(5), 08:00-19:00. Vigora a partir de 27/10/2026.
-- Rodar no Cloud SQL Studio (banco materlux, usuário postgres) junto com o deploy.
-- A linha da segunda é MOVIDA para terça (preserva room_id e horários).
-- Agendamentos já existentes em segundas NÃO são alterados: serão remarcados à mão.

BEGIN;

UPDATE medical.professional_schedules
   SET day_of_week = 2
 WHERE professional_id = 1 AND day_of_week = 1;

-- Terça 20/10/2026 (dia do deploy): ainda NÃO atende; a grade só vale de 27/10 em diante.
-- (Sequência defasada é um gotcha conhecido deste banco restaurado — ver CLAUDE.md.)
SELECT setval(pg_get_serial_sequence('medical.professional_timeoff', 'id'),
              (SELECT COALESCE(max(id), 1) FROM medical.professional_timeoff));

INSERT INTO medical.professional_timeoff (professional_id, start_timestamp, end_timestamp, reason)
SELECT 1, TIMESTAMPTZ '2026-10-20 00:00:00-03', TIMESTAMPTZ '2026-10-21 00:00:00-03',
       'Nova grade (terças) só vale a partir de 27/10/2026'
WHERE NOT EXISTS (
    SELECT 1 FROM medical.professional_timeoff
     WHERE professional_id = 1
       AND start_timestamp = TIMESTAMPTZ '2026-10-20 00:00:00-03'
);

COMMIT;

-- Conferência (deve mostrar 2, 3 e 5):
SELECT day_of_week, start_time, end_time FROM medical.professional_schedules
 WHERE professional_id = 1 ORDER BY day_of_week;

-- Desfazer (se precisar voltar às segundas):
--   UPDATE medical.professional_schedules SET day_of_week = 1
--    WHERE professional_id = 1 AND day_of_week = 2;
--   DELETE FROM medical.professional_timeoff
--    WHERE professional_id = 1 AND start_timestamp = TIMESTAMPTZ '2026-10-20 00:00:00-03';
