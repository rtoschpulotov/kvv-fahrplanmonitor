# Spark-Umgebung für Phase 5.
# Autor: Rustam T.
#
# Basis ist das offizielle Image der Apache Software Foundation, mit fest
# eingetragener Version. "latest" wäre bequem, aber dann rechnet derselbe Code
# in einem Jahr mit einem anderen Spark, und die Messwerte im README wären
# nicht mehr nachvollziehbar.
#
# 4.2.1 und nicht die ganz neue 4.3.0: Die war zum Zeitpunkt der Entscheidung
# (12.11.2026) erst eine Woche alt. Java 21, weil das die aktuelle
# Langzeitversion ist, die das Image anbietet.
FROM apache/spark:4.2.1-scala2.13-java21-python3-ubuntu

USER root

# Python im Image ist 3.10. Pandas 3 braucht 3.11, deshalb hier Pandas 2.3.
# Die Pandas-Logik des Projekts läuft mit beiden (geprüft mit allen Tests
# im Container). Pandas wird im Container nur für den Ergebnisvergleich und
# zum Einlesen der Register-CSV gebraucht.
RUN pip3 install --no-cache-dir \
        pandas==2.3.3 \
        pyarrow==23.0.0 \
        "psycopg[binary]==3.3.8" \
        python-dotenv==1.2.3 \
        psutil==7.2.2 \
        pytest==9.2.0

# JDBC-Treiber für PostgreSQL. Spark bringt keinen mit. Liegt er in
# /opt/spark/jars, findet Spark ihn ohne weitere Einstellung. ADD aus dem
# Netz legt die Datei nur für root lesbar an, deshalb danach chmod. Sonst
# fände der Benutzer spark, unter dem die Jobs laufen, den Treiber nicht.
ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar /opt/spark/jars/
RUN chmod 644 /opt/spark/jars/postgresql-42.7.14.jar

# Das Image legt PySpark unter /opt/spark/python ab, aber nicht in den
# Suchpfad von Python. Mit diesen beiden Pfaden geht "python3 spark/job.py"
# direkt, ohne spark-submit.
ENV PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.9-src.zip \
    PYTHONDONTWRITEBYTECODE=1

USER spark
WORKDIR /opt/kvv
