FROM eclipse-temurin:17-jre@sha256:1824944ef1bd572d1ff0952afeb2fec7931d77c972c4fbc4dfcdf89f758fb490
WORKDIR /app
ARG WGET_VERSION=1.25.0-2ubuntu4.4
RUN apt-get update \
    && apt-get install --yes --no-install-recommends "wget=${WGET_VERSION}" \
    && rm -rf /var/lib/apt/lists/*
COPY app.jar app.jar
EXPOSE 8102
ENTRYPOINT ["java", "-jar", "app.jar"]
