FROM eclipse-temurin:17-jre-alpine@sha256:02320dd4ce20e243dfb915c686089cf9315c763084fafbb12d5c9993aee18b57
WORKDIR /app
RUN apk add --no-cache curl
COPY target/document-generation-gateway-1.0.0.jar app.jar
EXPOSE 8092
ENTRYPOINT ["java", "-jar", "app.jar"]
