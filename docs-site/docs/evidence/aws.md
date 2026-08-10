# AWS capacity decision

Pricing checked: **10 August 2026**
Region/basis: **eu-west-2 (London), Linux/x86, On-Demand, 730 hours/month**

## Current recommendation

Use Amazon ECS on a single EC2 `m7i.2xlarge` (8 vCPU, 32 GiB) only as the first
bounded public-beta candidate. Its calculated compute price is **$340.33/month**.
It is not highly available and has not been benchmarked on AWS.

## Alternatives

| Stage | Candidate | Intended use | Evidence | Compute/month | Status |
| --- | --- | --- | --- | ---: | --- |
| Development | 16 logical CPUs / 32 GiB local | Full stack engineering | Measured host | local | Current |
| Private beta experiment | `t3.xlarge` | Tightly capped low concurrency | Calculated; CPU below 10-session peak | $137.82 | Risk accepted only with alarms |
| Small public beta | ECS/EC2 `m7i.2xlarge` | Bounded initial deployment | Calculated from local floor/peak | $340.33 | Candidate |
| Availability/growth | Multiple nodes / hot-service scaling | Failure and scaling headroom | Not benchmarked | unknown | Requires further benchmark |

Compute is not the AWS bill. EBS/RDS, object storage, load balancing, public
IPv4, NAT/data transfer, DNS, logs, backups, security services, support and tax
are excluded.

See `docs/aws-capacity-decision-2026-08-10.md` for official source links,
option calculations and scaling gates.
