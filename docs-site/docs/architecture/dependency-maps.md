# Dependency maps

Arrows show runtime HTTP calls on `develop`, not build-time generated-client dependencies.

## Account and profile

```mermaid
flowchart LR
  Client[Client BFF] --> UMG[User Management Gateway]
  UMG --> Auth[Authentication Service]
  UMG --> Profile[User Profile Service]
  Auth --> AuthDB[(authentication)]
  Profile --> ProfileDB[(user_profile)]
  Profile -->|JWKS| Auth
```

## Job search and applications

```mermaid
flowchart LR
  Client[Client BFF] --> Finder[Job Finder Gateway]
  Finder --> Profile[User Profile]
  Finder --> Jobs[Job Service]
  Finder --> Tracker[Application Tracker]
  Jobs --> Reed[Reed Gateway]
  Jobs --> Adzuna[Adzuna Gateway]
  Jobs --> JSearch[JSearch Gateway]
  Jobs --> Matching[Job Matching]
  Matching --> Tracker
  Jobs --> JobDB[(job_service<br/>saved jobs)]
  Tracker --> AppDB[(application_tracker)]
```

## Document generation

```mermaid
flowchart LR
  Client[Client BFF] --> DG[Document Generation Gateway]
  DG --> Job[Job Service]
  DG --> Profile[User Profile]
  DG --> CV[CV/Cover Letter]
  DG --> Store[Document Store]
  DG --> Export[Document Export]
  DG --> Tracker[Application Tracker]
  DG --> Payment[Payment Service]
  CV --> LLM[LLM Gateway]
  CV --> Payment
  Export --> Store
  DG --> OpDB[(document_generation)]
  Store --> DocDB[(document_store)]
  Store --> Objects[(object bytes)]
```

## Reporting and payment

```mermaid
flowchart LR
  Client[Client BFF] --> RG[Reporting Gateway]
  RG --> Report[Reporting Service]
  Report --> Tracker[Application Tracker]
  Report --> Store[Document Store]
  Report --> Profile[User Profile]

  Client -. payment disabled .-> PG[Payment Gateway]
  PG --> Pay[Payment Service]
  PG --> Stripe[Stripe Gateway]
  Stripe --> Pay
  Pay --> PayDB[(payment)]
```

## Fixture boundary

```mermaid
flowchart TB
  SD[System Data Service]
  SD -. fixture responses .-> Reed[Reed]
  SD -. fixture responses .-> Adzuna[Adzuna]
  SD -. fixture responses .-> JSearch[JSearch]
  SD -. fixture responses .-> Postcode[Postcode.io]
  SD -. fixture responses .-> LLM[LLM]
  SD -. fixture responses .-> Stripe[Stripe]
  SD -->|guarded reset/seed/verify| Auth[Authentication]
  SD --> Profile[User Profile]
  SD --> Tracker[Application Tracker]
  SD --> Store[Document Store]
  SD --> Pay[Payment]
```

System Data is deliberately outside production ownership. It serves versioned synthetic provider responses and coordinates service-owned non-production management APIs. It does not bypass APIs or share databases.
