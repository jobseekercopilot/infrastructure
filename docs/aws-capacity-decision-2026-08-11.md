# AWS capacity decision — 2026-08-11

## Decision

For a bounded public beta, retain **Amazon ECS on one x86 EC2 `m7i.2xlarge`**
(8 vCPU, 32 GiB) as the minimum calculated starting shape. Operate initially
around **15 concurrently active DISCOVER journeys**, not 25, and alert on
latency and CPU before allowing more load. This is a single-node, non-HA
starting point, not a production availability design.

The fresh local benchmark functionally completed 25/25 sessions, but that is a
safety result rather than a comfortable operating point: session p95 was
59.45 seconds and throughput had already peaked at 10 sessions. A 50-session
run was therefore correctly not attempted.

## Evidence boundary

- **Measured locally:** Docker resources and browser-journey latency on a
  16-logical-CPU, 30.63-GiB Linux host.
- **Measured on AWS:** nothing. No AWS workload was run and no AWS resources
  were created.
- **Calculated:** instance-hour and 730-hour monthly costs using the dated AWS
  price-list rate below.
- **Modelled:** the operational concurrency cap and future multi-node options.

The local browser workers consume host resources but are not included in
Docker resource measurements. Real user browsers would not run on the ECS
host, so the local 25-session slowdown cannot be assigned solely to the service
stack. Conversely, this is not permission to claim better cloud capacity
without measuring it.

## Fresh measured ladder

| Active sessions | Completed | Session p95 | Response p95 | Response p99 | Peak Docker CPU | Peak Docker memory |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1/1 | 5.97 s | 182 ms | — | 317% | 8.01 GiB |
| 5 | 5/5 | 10.34 s | 571 ms | 1,107 ms | 259% | 8.14 GiB |
| 10 | 10/10 | 17.00 s | 709 ms | 970 ms | 783% | 8.35 GiB |
| 15 | 15/15 | 25.97 s | 472 ms | 961 ms | 714% | 8.42 GiB |
| 20 | 20/20 | 40.43 s | 609 ms | 2,248 ms | 702% | 8.66 GiB |
| 25 | 25/25 | 59.45 s | 546 ms | 1,207 ms | 567% | 8.64 GiB |

There were zero application errors, restarts, OOM kills and unhealthy
containers in the final ladder. One of ten intended Docker-stats observations
at 25 sessions exceeded the sampler's 20-second limit; the remaining nine
samples and the error are retained transparently.

The previous 0/25 result was traced to a frontend card being destroyed when an
immutable refresh introduced a canonical identifier. Tracking cards by their
stable provider job ID fixed that boundary. The final 25-session run did not
expose a failing service or endpoint. Its limiting signal is end-to-end latency
and declining throughput, not memory exhaustion.

At 25 sessions the highest service CPU peaks were application tracker 89.73%,
authentication 76.02%, user profile 66.68% and user management gateway 63.84%.
ClamAV remained the largest fixed-memory container at about 0.95 GiB. The
stack's roughly 8-GiB idle floor is distributed across many JVM services,
databases and support containers rather than one leak.

## Shape and cost calculation

The cost basis remains the official AWS Price List snapshot retrieved on
2026-08-10 for London (`eu-west-2`), Linux/x86, shared tenancy and On-Demand.
AWS documents the Price List API as the source for SKU-level pricing and notes
that the service pricing page takes precedence if the two differ:

- [AWS Price List API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)
- [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [ECS pricing](https://aws.amazon.com/ecs/pricing/)
- [Fargate pricing](https://aws.amazon.com/fargate/pricing/)

| Candidate | Resources | Rate | Calculated 730-hour month | Decision |
|---|---:|---:|---:|---|
| `t3.xlarge` | 4 vCPU / 16 GiB | $0.1888/h | $137.82 | Private test only; burstable CPU and narrow system headroom. |
| `r7i.xlarge` | 4 vCPU / 32 GiB | $0.3108/h | $226.88 | Memory-rich but below the measured 7.83-logical-CPU peak. |
| `m7i.2xlarge` | 8 vCPU / 32 GiB | $0.4662/h | $340.33 | Minimum calculated public-beta starting shape. |
| Two `m7i.2xlarge` nodes | 16 vCPU / 64 GiB total | $0.9324/h | $680.65 | Modelled HA/scale candidate; not benchmarked. |

ECS on EC2 adds no separate ECS orchestration fee. These figures exclude EBS,
RDS, load balancing, NAT, public IPv4, DNS, logs, backups, support, tax and data
transfer. Fargate and EKS remain possible later, but the current 36-container
topology needs per-service reservations and database separation before either
comparison is operationally credible.

## AWS workload-validation status

Real AWS validation was not possible in this run. The private secrets file has
no AWS access keys, there is no local AWS credentials file or AWS CLI, and the
only AWS configuration found is an SSO-profile definition without an active
credential path. The repository also has no ready, approved ephemeral
benchmark deployment for the complete stack. No substitute local result is
labelled AWS-tested; no cloud resource was created; AWS validation spend is
**$0.00**.

Before changing the recommendation, deploy the intended ECS/RDS/network shape
in `eu-west-2`, estimate and cap spend, measure 10/15/20 sessions, then destroy
temporary resources. Production task reservations, database architecture,
load-balancer health checks, observability and recovery objectives must be
defined first.
