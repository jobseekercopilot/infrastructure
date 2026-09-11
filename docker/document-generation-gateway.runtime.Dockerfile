FROM eclipse-temurin:17-jre-alpine@sha256:90b7615cb81e3a75f69124fb480e48981c7d56dbc9f32c614d789d3a1c3e32fe
# Refresh the pinned runtime's OpenSSL (CVE-2026-14456) and libexpat
# (CVE-2026-76956/76641/76957/66046 - hash-flooding DoS) to fixed builds.
RUN apk add --no-cache --upgrade \
    libcrypto3=3.5.8-r0 \
    libssl3=3.5.8-r0 \
    expat=2.8.4-r0 \
    openssl=3.5.8-r0
WORKDIR /app
COPY app.jar app.jar
EXPOSE 8092
ENTRYPOINT ["java", "-jar", "app.jar"]
