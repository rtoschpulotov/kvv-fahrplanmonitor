-- Beispielabfragen auf das Sternschema.
-- Autor: Rustam T.
--
-- Liegt bewusst in einem Unterordner: Der Postgres-Container führt beim
-- ersten Start nur die Dateien direkt in sql/ aus, diese hier nicht.
-- Aufruf zum Beispiel:
--   docker compose exec -T postgres psql -U kvv -d kvv_fahrplan < sql/abfragen/beispiele.sql

-- 1. Wie hieß eine Station zu einem bestimmten Zeitpunkt?
--    Das ist die Frage, für die SCD2 da ist: eine einfache Bereichsabfrage.
SELECT station_id, name, gemeinde, gueltig_von, gueltig_bis
  FROM dim_haltestelle
 WHERE station_id = 'Pde:08212:89'
   AND TIMESTAMPTZ '2026-11-05 12:00+01' >= gueltig_von
   AND TIMESTAMPTZ '2026-11-05 12:00+01' <  gueltig_bis;

-- 2. Welche Versionen gibt es überhaupt (alles, was sich je geändert hat)?
SELECT station_id, count(*) AS versionen, string_agg(name, ' -> ' ORDER BY gueltig_von) AS namen
  FROM dim_haltestelle
 GROUP BY station_id
HAVING count(*) > 1;

-- 3. Was neu dazukam, je Stand
SELECT s.stand_id, count(h.*) AS neue_stationen
  FROM dim_stand s
  LEFT JOIN dim_haltestelle h ON h.stand_sk_erstmals = s.stand_sk AND s.stand_sk > 1
 GROUP BY s.stand_id ORDER BY s.stand_id;

-- 4. Abfahrten am Di 10.11.2026 laut jedem Stand, der diesen Tag kennt.
--    Ändert der KVV seinen Plan für einen Tag, sieht man es hier.
SELECT s.stand_id, sum(f.anzahl) AS abfahrten
  FROM fakt_abfahrten f
  JOIN dim_stand s USING (stand_sk)
 WHERE f.datum = '2026-11-10'
 GROUP BY s.stand_id ORDER BY s.stand_id;

-- 5. Was hat sich zwischen zwei Ständen für diesen Tag geändert, je Linie und Stunde?
--    Verglichen wird über die fachlichen Schlüssel (station_id, route_id),
--    nicht über die Surrogatschlüssel. Hat eine Haltestelle zwischen den
--    Ständen eine neue Version bekommen, hat sie einen neuen _sk, ist aber
--    dieselbe Haltestelle.
WITH tag AS (
    SELECT f.stand_sk, h.station_id, l.route_id, f.stunde, f.anzahl
      FROM fakt_abfahrten f
      JOIN dim_haltestelle h USING (haltestelle_sk)
      JOIN dim_linie l USING (linie_sk)
     WHERE f.datum = '2026-11-10'
), a AS (SELECT * FROM tag WHERE stand_sk = (SELECT stand_sk FROM dim_stand WHERE stand_id = '2026-11-05T122034Z')),
   b AS (SELECT * FROM tag WHERE stand_sk = (SELECT stand_sk FROM dim_stand WHERE stand_id = '2026-11-06T120647Z'))
SELECT l.kurzname, coalesce(a.stunde, b.stunde) AS stunde,
       sum(coalesce(b.anzahl, 0) - coalesce(a.anzahl, 0)) AS differenz
  FROM a FULL JOIN b USING (station_id, route_id, stunde)
  JOIN dim_linie l ON l.route_id = coalesce(a.route_id, b.route_id) AND l.ist_aktuell
 WHERE a.anzahl IS DISTINCT FROM b.anzahl
 GROUP BY 1, 2 ORDER BY 1, 2;

-- 6. Abfahrten je Gemeinde und Tageszeitband an einem Werktag außerhalb der Ferien,
--    jeweils nach dem neuesten Stand.
SELECT h.gemeinde, st.band, sum(f.anzahl) AS abfahrten
  FROM fakt_abfahrten f
  JOIN dim_datum d USING (datum)
  JOIN dim_stunde st USING (stunde)
  JOIN dim_haltestelle h USING (haltestelle_sk)
 WHERE f.stand_sk = (SELECT max(stand_sk) FROM dim_stand)
   AND d.datum = '2026-11-10'
   AND d.tagestyp = 'Werktag' AND NOT d.ist_schulferien
   AND h.gemeinde IN ('Karlsruhe', 'Ettlingen', 'Muggensturm')
 GROUP BY h.gemeinde, st.band, st.band_sort
 ORDER BY h.gemeinde, st.band_sort;
