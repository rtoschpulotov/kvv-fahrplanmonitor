-- Stände nur in zeitlicher Reihenfolge.
-- Autor: Rustam T.
--
-- SCD2 schreibt Geschichte fort: Jede neue Version schließt die vorige zum
-- Zeitpunkt des neuen Stands. Lädt man einen älteren Stand nach einem
-- neueren, würde eine Version "rückwärts" geschlossen, und gueltig_von läge
-- hinter gueltig_bis. Die Historie wäre kaputt.
--
-- Das soll nicht von meiner Aufmerksamkeit abhängen. Deshalb lehnt die
-- Datenbank selbst jeden Stand ab, der nicht jünger ist als alle bisher
-- geladenen. Der Python-Lader sortiert zwar auch, aber diese Sperre greift
-- auch dann, wenn jemand von Hand einfügt.

CREATE OR REPLACE FUNCTION pruefe_stand_reihenfolge() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    juengster timestamptz;
BEGIN
    -- Sperre auf die Tabelle, damit zwei gleichzeitige Läufe sich nicht
    -- gegenseitig überholen können.
    LOCK TABLE dim_stand IN SHARE ROW EXCLUSIVE MODE;
    SELECT max(abgerufen_utc) INTO juengster FROM dim_stand;
    IF juengster IS NOT NULL AND NEW.abgerufen_utc <= juengster THEN
        RAISE EXCEPTION 'Stand % (%) ist nicht jünger als der jüngste geladene Stand (%). '
                        'Ältere Stände lassen sich nur mit einem Neuaufbau laden.',
                        NEW.stand_id, NEW.abgerufen_utc, juengster;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS tr_stand_reihenfolge ON dim_stand;
CREATE TRIGGER tr_stand_reihenfolge
    BEFORE INSERT ON dim_stand
    FOR EACH ROW EXECUTE FUNCTION pruefe_stand_reihenfolge();
