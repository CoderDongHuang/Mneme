ARG MAVEN_BASE_IMAGE=maven:3.9-eclipse-temurin-17
ARG JAVA_BASE_IMAGE=eclipse-temurin:17-jre-alpine
FROM ${MAVEN_BASE_IMAGE} AS build

WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests

FROM ${JAVA_BASE_IMAGE}

WORKDIR /app
COPY --from=build /app/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
