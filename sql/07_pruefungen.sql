-- Prüfabfragen. Jede Sicht listet Verstöße. Leer heißt: in Ordnung.
-- Autor: Rustam T.
--
-- Aufruf: SELECT * FROM v_pruefung;   (eine Zeile je Prüfung mit Trefferzahl)
-- Der Lader ruft das nach jedem Lauf auf und meldet jede Prüfung mit Treffern.

-- 1. Pro fachlichem Schlüssel höchstens eine aktuelle Version
CREATE OR REPLACE VIEW v_pruefung_mehrfach_aktuell AS
SELECT 'haltestelle' AS dimension, station_id AS schluessel, count(*) AS anzahl
  FROM dim_haltestelle WHERE ist_aktuell GROUP BY station_id HAVING count(*) > 1
UNION ALL
SELECT 'linie', route_id, count(*)
  FROM dim_linie WHERE ist_aktuell GROUP BY route_id HAVING count(*) > 1;

-- 2. Keine überlappenden Gültigkeitszeiträume. Zwei Versionen desselben
-- Schlüssels überlappen, wenn jede beginnt, bevor die andere endet.
-- Wegen gueltig_bis ausschließlich ist "Ende der einen = Anfang der anderen"
-- keine Überlappung.
CREATE OR REPLACE VIEW v_pruefung_ueberlappung AS
SELECT 'haltestelle' AS dimension, a.station_id AS schluessel,
       a.haltestelle_sk AS version_a, b.haltestelle_sk AS version_b
  FROM dim_haltestelle a
  JOIN dim_haltestelle b
    ON a.station_id = b.station_id
   AND a.haltestelle_sk < b.haltestelle_sk
   AND a.gueltig_von < b.gueltig_bis
   AND b.gueltig_von < a.gueltig_bis
UNION ALL
SELECT 'linie', a.route_id, a.linie_sk, b.linie_sk
  FROM dim_linie a
  JOIN dim_linie b
    ON a.route_id = b.route_id
   AND a.linie_sk < b.linie_sk
   AND a.gueltig_von < b.gueltig_bis
   AND b.gueltig_von < a.gueltig_bis;

-- 3. Jede Faktzeile findet ihre Dimensionsversion, und zwar die, die zum
-- Abrufzeitpunkt ihres Stands galt. Dass die Version existiert, garantiert
-- schon der Fremdschlüssel. Ob es die richtige ist, prüft erst diese Sicht.
CREATE OR REPLACE VIEW v_pruefung_fakt_version AS
SELECT f.stand_sk, f.datum, f.stunde, f.haltestelle_sk, f.linie_sk
  FROM fakt_abfahrten f
  JOIN dim_stand s USING (stand_sk)
  LEFT JOIN dim_haltestelle h
    ON h.haltestelle_sk = f.haltestelle_sk
   AND s.abgerufen_utc >= h.gueltig_von AND s.abgerufen_utc < h.gueltig_bis
  LEFT JOIN dim_linie l
    ON l.linie_sk = f.linie_sk
   AND s.abgerufen_utc >= l.gueltig_von AND s.abgerufen_utc < l.gueltig_bis
 WHERE h.haltestelle_sk IS NULL OR l.linie_sk IS NULL;

-- 4. Jeder Stand hat Fakten, und nur Tage aus seinem Horizont.
CREATE OR REPLACE VIEW v_pruefung_stand_fakten AS
SELECT s.stand_sk, s.stand_id, count(f.stand_sk) AS faktzeilen,
       min(f.datum) AS erster_tag, max(f.datum) AS letzter_tag
  FROM dim_stand s
  LEFT JOIN fakt_abfahrten f USING (stand_sk)
 GROUP BY s.stand_sk, s.stand_id, s.horizont_von, s.horizont_bis
HAVING count(f.stand_sk) = 0
    OR min(f.datum) < s.horizont_von
    OR max(f.datum) > s.horizont_bis;

-- Überblick: eine Zeile je Prüfung
CREATE OR REPLACE VIEW v_pruefung AS
SELECT 'mehrfach aktuell' AS pruefung, count(*) AS treffer FROM v_pruefung_mehrfach_aktuell
UNION ALL SELECT 'überlappende Zeiträume', count(*) FROM v_pruefung_ueberlappung
UNION ALL SELECT 'Fakt ohne passende Version', count(*) FROM v_pruefung_fakt_version
UNION ALL SELECT 'Stand ohne oder mit falschen Fakten', count(*) FROM v_pruefung_stand_fakten;
