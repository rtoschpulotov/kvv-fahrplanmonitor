-- fakt_abfahrten aus stg_abfahrten befüllen.
-- Autor: Rustam T.
--
-- Jede Faktzeile zeigt auf die Version der Haltestelle und der Linie, die
-- zum Abrufzeitpunkt des Stands galt. Weil die SCD2-Prozeduren vorher
-- gelaufen sind, ist das beim Laden immer die gerade aktuelle Version. Ich
-- frage trotzdem über den Zeitpunkt ab und nicht über ist_aktuell: So steht
-- im Code, was gemeint ist, und es funktioniert auch beim Neuaufbau.
--
-- Findet eine Zeile keine Version, wäre sie beim INNER JOIN einfach weg.
-- Deshalb zähle ich vorher und nachher und breche ab, wenn etwas fehlt.

CREATE OR REPLACE PROCEDURE lade_fakt(p_stand_sk integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_zeit     timestamptz;
    v_erwartet bigint;
    v_geladen  bigint;
BEGIN
    SELECT abgerufen_utc INTO STRICT v_zeit FROM dim_stand WHERE stand_sk = p_stand_sk;
    SELECT count(*) INTO v_erwartet FROM stg_abfahrten;

    INSERT INTO fakt_abfahrten (stand_sk, datum, stunde, haltestelle_sk, linie_sk, anzahl)
    SELECT p_stand_sk, a.datum, a.stunde, h.haltestelle_sk, l.linie_sk, a.anzahl
      FROM stg_abfahrten a
      JOIN dim_haltestelle h
        ON h.station_id = a.station_id
       AND v_zeit >= h.gueltig_von AND v_zeit < h.gueltig_bis
      JOIN dim_linie l
        ON l.route_id = a.route_id
       AND v_zeit >= l.gueltig_von AND v_zeit < l.gueltig_bis;

    GET DIAGNOSTICS v_geladen = ROW_COUNT;
    IF v_geladen <> v_erwartet THEN
        RAISE EXCEPTION 'Stand %: % Abfahrtszeilen erwartet, aber nur % haben eine Haltestellen- und Linienversion gefunden',
                        p_stand_sk, v_erwartet, v_geladen;
    END IF;
END $$;
