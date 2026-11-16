# Spark 4.2.0 with Delta Lake 4.4.1 (which supports PySpark 4.0.1 to 4.2.0). Jars checked against pinned SHA-256s.
FROM apache/spark:4.2.0-python3
ADD --chmod=644 --checksum=sha256:2b1d2cd411bf0bbced64b96fe621f8ffce7bb6e394c8064ab783fc6edce449be \
    https://repo1.maven.org/maven2/io/delta/delta-spark_2.13/4.4.1/delta-spark_2.13-4.4.1.jar /opt/spark/jars/
ADD --chmod=644 --checksum=sha256:f585818d646cb3625b305270ec24f3e6f0b6ea63ed9bac1ae8f340f8faaeae8f \
    https://repo1.maven.org/maven2/io/delta/delta-storage/4.4.1/delta-storage-4.4.1.jar /opt/spark/jars/
USER root
# The Python side of Delta (delta.tables.DeltaTable); PySpark itself comes with the image
RUN pip install --no-cache-dir --no-deps delta-spark==4.4.1
USER spark
COPY log4j2.properties /opt/spark/conf/log4j2.properties
