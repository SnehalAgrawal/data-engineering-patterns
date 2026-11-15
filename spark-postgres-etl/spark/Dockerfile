# Spark's official image plus the PostgreSQL JDBC driver, checked against a pinned SHA-256.
FROM apache/spark:4.2.1-python3
ADD --chmod=644 --checksum=sha256:73914527305a40cce504b0d3d90b23caf565136912d607ae8ae7c5895512332c \
    https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar /opt/spark/jars/
# Log warnings and errors only (Spark's built-in default logs INFO), so job output stays readable
COPY log4j2.properties /opt/spark/conf/log4j2.properties
