-- Prüfabfragen für Phase 4. Erweitert v_pruefung aus 07_pruefungen.sql.
-- Autor: Rustam T.

-- 5. Jede Änderung liegt im Fenster ihres Standpaars: nicht vor dem Abruf
-- des neuen Stands und nicht nach fenster_bis.
CREATE OR REPLACE VIEW v_pruefung_fenster AS
SELECT a.aenderung_id, a.standpaar_sk, a.kalendertag
  FROM fakt_aenderung a
  JOIN dim_standpaar p USING (standpaar_sk)
 WHERE a.kalendertag < (p.fenster_ab AT TIME ZONE 'Europe/Berlin')::date
    OR a.kalendertag > p.fenster_bis;

-- 6. Standpaare sind direkte Nachbarn: Zwischen alt und neu liegt kein
-- anderer geladener Stand, und jeder Stand außer dem ersten hat ein Paar.
CREATE OR REPLACE VIEW v_pruefung_standfolge AS
WITH folge AS (
    SELECT stand_sk, lag(stand_sk) OVER (ORDER BY abgerufen_utc) AS vorher FROM dim_stand
)
SELECT f.vorher AS stand_sk_alt, f.stand_sk AS stand_sk_neu, p.standpaar_sk
  FROM folge f
  FULL JOIN dim_standpaar p ON p.stand_sk_alt = f.vorher AND p.stand_sk_neu = f.stand_sk
 WHERE (f.vorher IS NOT NULL AND p.standpaar_sk IS NULL)      -- Paar fehlt
    OR (f.stand_sk IS NULL);                                 -- Paar, das keine Nachbarn verbindet

CREATE OR REPLACE VIEW v_pruefung AS
SELECT 'mehrfach aktuell' AS pruefung, count(*) AS treffer FROM v_pruefung_mehrfach_aktuell
UNION ALL SELECT 'überlappende Zeiträume', count(*) FROM v_pruefung_ueberlappung
UNION ALL SELECT 'Fakt ohne passende Version', count(*) FROM v_pruefung_fakt_version
UNION ALL SELECT 'Stand ohne oder mit falschen Fakten', count(*) FROM v_pruefung_stand_fakten
UNION ALL SELECT 'Änderung außerhalb des Fensters', count(*) FROM v_pruefung_fenster
UNION ALL SELECT 'Standpaar fehlt oder falsch', count(*) FROM v_pruefung_standfolge;
