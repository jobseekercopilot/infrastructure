# Job Seeker Copilot - Build Tools

Shared build configuration, dependency management, and code quality tools for all Job Seeker Copilot backend microservices.

## Overview

This project provides a centralized Maven parent POM that standardizes build configuration, dependency versions, and code quality checks across all microservices in the Job Seeker Copilot ecosystem.

## Features

- **Centralized Dependency Management**: Consistent versions for Spring Boot, Lombok, JWT, and testing libraries
- **Code Quality Enforcement**: Integrated Checkstyle, PMD, and SpotBugs plugins
- **Java 17 Support**: Configured for modern Java development
- **Spring Boot 3.2.0**: Latest stable Spring Boot version
- **Standardized Build Process**: Common Maven plugin configurations

## Technologies

- **Java 17**
- **Maven** (Parent POM)
- **Spring Boot 3.2.0**
- **Lombok 1.18.32**
- **JJWT 0.12.3** (JWT authentication)
- **Spring Cloud Contract WireMock 4.1.0** (Testing)

## Code Quality Tools

### Checkstyle 10.12.5 via Maven Checkstyle Plugin 3.6.0
- Enforces coding standards and style guidelines
- Configured via `checkstyle.xml`
- Runs during the `verify` phase

### PMD
- Static code analysis for potential bugs and code smells
- Configured via `pmd-rulesets.xml`
- Includes CPD (Copy-Paste Detection)
- Runs during the `verify` phase

### SpotBugs (4.8.2.0)
- Detects potential bugs and security vulnerabilities
- Configured via `spotbugs-exclude.xml`
- Runs during the `verify` phase

**Note**: All code quality checks are configured with `failOnViolation=false` to allow gradual adoption. Projects can enable strict enforcement by setting these properties to `true`.

## Usage

### As a Parent POM

Add this as the parent in your microservice's `pom.xml`:

```xml
<parent>
    <groupId>com.jobseekercopilot</groupId>
    <artifactId>job-seeker-copilot-build</artifactId>
    <version>1.0.0</version>
</parent>
```

### Dependency Management

All dependencies are managed centrally. Simply declare dependencies without versions:

```xml
<dependencies>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
        <groupId>org.projectlombok</groupId>
        <artifactId>lombok</artifactId>
        <optional>true</optional>
    </dependency>
</dependencies>
```

### Available Dependencies

- Spring Boot dependencies (auto-imported from Spring Boot BOM)
- Lombok
- JJWT (API, implementation, Jackson)
- Spring Cloud Contract WireMock (test scope)

## Project Structure

```
build-tools/
├── pom.xml                          # Parent POM with dependency and plugin management
├── README.md                        # This file
└── src/main/resources/
    ├── checkstyle.xml               # Checkstyle configuration
    ├── pmd-rulesets.xml             # PMD rules configuration
    └── spotbugs-exclude.xml         # SpotBugs exclusion filters
```

## Building

```bash
mvn -Dcheckstyle.skip=true validate
```

This validates the inherited parent-POM model only. The rules are currently
stored beside the POM and are not packaged for consumers; consequently the
standalone quality executions are not a release gate. Publishing the parent
and its rule assets, proving consumer resolution, and making the checks
fail-closed are tracked in the Infrastructure epic.

## Publishing to Maven Repository

To use this across multiple projects, publish it to your Maven repository (Nexus, Artifactory, etc.):

```bash
mvn clean deploy
```

Do not deploy version `1.0.0` until the publication issue is complete.

## Configuration Properties

Customize the build by overriding these properties in your child POM:

| Property | Default | Description |
|----------|---------|-------------|
| `java.version` | 17 | Java compiler version |
| `spring-boot.version` | 3.2.0 | Spring Boot version |
| `checkstyle.failOnViolation` | false | Fail build on Checkstyle violations |
| `pmd.failOnViolation` | false | Fail build on PMD violations |
| `spotbugs.failOnError` | false | Fail build on SpotBugs errors |
| `spotbugs.effort` | medium | SpotBugs analysis effort (max, medium, min) |
| `spotbugs.threshold` | medium | SpotBugs confidence threshold (high, medium, low) |

## Contributing

When modifying this build configuration:

1. Test changes with at least one microservice
2. Ensure all code quality tools pass
3. Update version numbers following semantic versioning
4. Document any breaking changes

## License

[Add your license here]

## Contact

[Add contact information or links to documentation]
