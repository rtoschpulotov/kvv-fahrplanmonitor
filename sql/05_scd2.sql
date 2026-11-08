-- Der SCD2-Schritt: Dimensionen auf den Stand bringen, der in stg_* liegt.
-- Autor: Rustam T.
--
-- Vier Fälle je fachlichem Schlüssel:
--   1. neu im Stand                 -> neue Version einfügen
--   2. da und unverändert           -> nichts tun
--   3. da, aber Attribute geändert  -> alte Version schließen, neue einfügen
--   4. aus dem Stand verschwunden   -> alte Version schließen, ohne Nachfolger
--
-- Das geht mit genau zwei Anweisungen:
--
--   UPDATE: Schließe jede aktuelle Version, zu der es im Stand keine Zeile mit
--           demselben Schlüssel UND demselben Hash gibt. Das trifft Fall 3
--           (Hash anders) und Fall 4 (Schlüssel fehlt). Fall 2 bleibt offen.
--
--   INSERT: Füge jede Zeile des Stands ein, deren Schlüssel jetzt keine
--           aktuelle Version mehr hat. Das trifft Fall 1 (gab es nie) und
--           Fall 3 (wurde eben geschlossen). Fall 2 hat noch eine aktuelle
--           Version und wird übersprungen.
--
-- Die Reihenfolge ist wichtig: erst schließen, dann einfügen. Andersherum
-- hätte in Fall 3 die alte Version noch ist_aktuell, und der INSERT würde
-- die neue nicht einfügen.
--
-- Eine Haltestelle, die verschwindet und zwei Wochen später wieder auftaucht,
-- bekommt eine neue Version mit einer Lücke davor. Zwischen gueltig_bis der
-- alten und gueltig_von der neuen Version gab es sie im Feed nicht.
--
-- Beide Prozeduren laufen in der Transaktion des Laders. Schlägt danach
-- etwas fehl (etwa das Laden der Fakten), wird alles zurückgerollt und die
-- Dimension bleibt, wie sie war.

CREATE OR REPLACE PROCEDURE scd2_haltestelle(p_stand_sk integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_zeit timestamptz;
BEGIN
    SELECT abgerufen_utc INTO STRICT v_zeit FROM dim_stand WHERE stand_sk = p_stand_sk;

    -- Fall 3 und 4: schließen
    UPDATE dim_haltestelle d
       SET gueltig_bis = v_zeit,
           ist_aktuell = false
     WHERE d.ist_aktuell
       AND NOT EXISTS (
            SELECT 1 FROM v_stg_haltestelle s
             WHERE s.station_id = d.station_id
               AND s.attr_hash  = d.attr_hash);

    -- Fall 1 und 3: einfügen
    INSERT INTO dim_haltestelle
           (station_id, name, lat, lon, gemeinde_ags, gemeinde, attr_hash,
            gueltig_von, gueltig_bis, ist_aktuell, stand_sk_erstmals)
    SELECT s.station_id, s.name, s.lat, s.lon, s.gemeinde_ags, s.gemeinde, s.attr_hash,
           v_zeit, '9999-12-31', true, p_stand_sk
      FROM v_stg_haltestelle s
     WHERE NOT EXISTS (
            SELECT 1 FROM dim_haltestelle d
             WHERE d.station_id = s.station_id
               AND d.ist_aktuell);
END $$;

CREATE OR REPLACE PROCEDURE scd2_linie(p_stand_sk integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_zeit timestamptz;
BEGIN
    SELECT abgerufen_utc INTO STRICT v_zeit FROM dim_stand WHERE stand_sk = p_stand_sk;

    UPDATE dim_linie d
       SET gueltig_bis = v_zeit,
           ist_aktuell = false
     WHERE d.ist_aktuell
       AND NOT EXISTS (
            SELECT 1 FROM v_stg_linie s
             WHERE s.route_id  = d.route_id
               AND s.attr_hash = d.attr_hash);

    INSERT INTO dim_linie
           (route_id, kurzname, langname, verkehrsmittel, betreiber_id, betreiber, attr_hash,
            gueltig_von, gueltig_bis, ist_aktuell, stand_sk_erstmals)
    SELECT s.route_id, s.kurzname, s.langname, s.verkehrsmittel, s.betreiber_id, s.betreiber, s.attr_hash,
           v_zeit, '9999-12-31', true, p_stand_sk
      FROM v_stg_linie s
     WHERE NOT EXISTS (
            SELECT 1 FROM dim_linie d
             WHERE d.route_id = s.route_id
               AND d.ist_aktuell);
END $$;
