-- Stunden 0 bis 23 mit Tageszeitband.
-- Autor: Rustam T.
--
-- Die Grenzen sind meine Festlegung, nicht die des KVV:
--   Nacht  0 bis 4 Uhr   (passt zum Abendfenster aus E11, das um 4 Uhr endet)
--   Früh   5 bis 8 Uhr   (Berufs- und Schulverkehr)
--   Tag    9 bis 17 Uhr
--   Abend 18 bis 23 Uhr
-- band_sort sorgt in Power BI dafür, dass die Bänder in Tagesreihenfolge
-- stehen und nicht alphabetisch.

INSERT INTO dim_stunde (stunde, band, band_sort)
SELECT h,
       CASE WHEN h <= 4 THEN 'Nacht' WHEN h <= 8 THEN 'Früh' WHEN h <= 17 THEN 'Tag' ELSE 'Abend' END,
       CASE WHEN h <= 4 THEN 4       WHEN h <= 8 THEN 1      WHEN h <= 17 THEN 2     ELSE 3 END
FROM generate_series(0, 23) AS h
ON CONFLICT (stunde) DO UPDATE SET band = EXCLUDED.band, band_sort = EXCLUDED.band_sort
WHERE (dim_stunde.band, dim_stunde.band_sort) IS DISTINCT FROM (EXCLUDED.band, EXCLUDED.band_sort);
