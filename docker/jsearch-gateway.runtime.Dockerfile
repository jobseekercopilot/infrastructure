FROM eclipse-temurin:17-jre-alpine@sha256:90b7615cb81e3a75f69124fb480e48981c7d56dbc9f32c614d789d3a1c3e32fe
WORKDIR /app
COPY app.jar app.jar
EXPOSE 8102
ENTRYPOINT ["java", "-jar", "app.jar"]
