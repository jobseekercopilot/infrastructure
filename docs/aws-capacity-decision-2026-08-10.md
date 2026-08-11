# AWS capacity decision — 2026-08-10

## Decision summary

For a bounded beta, prefer **Amazon ECS on one x86 EC2 instance** over plain
Docker, Fargate, EKS or Lambda. ECS adds no orchestration fee on the EC2 launch
type, preserves the current container model and allows service-level scaling
later. A single `m7i.2xlarge` (8 vCPU, 32 GiB) is the first configuration here
that has both memory headroom and enough CPU to resemble the highest successful
10-session measurement. It is not highly available.

Do not claim support for 25 concurrently active DISCOVER sessions. The measured
25-session run completed 0/25 journeys: response p95 reached 1.11 seconds and
every browser timed out waiting for job details. Containers did not restart,
become unhealthy or suffer OOM kills, so the first observed boundary is the
synchronous application path/latency budget rather than container memory.

## Evidence and sizing

Evidence comes from the reviewed JSON under
`benchmark-results/baseline/2026-08-10/` and the generated
`docs/capacity-report-2026-08-10.md`.

- Measured host: 16 logical x86 CPUs, 30.63 GiB RAM, Docker 29.6.1.
- Measured stack: 36 application, database and support containers; browser
  processes are excluded from container figures.
- Idle floor: 9.73 GiB average, 9.74 GiB peak container memory; 10.52% average
  and 27.47% peak aggregate Docker CPU.
- Single session: 9.87 GiB peak memory; response p95 89 ms; 1/1 passed.
- Five concurrent sessions: 9.91 GiB peak memory; response p95 164 ms; 5/5
  passed.
- Ten concurrent sessions: 9.96 GiB peak memory; response p95 273 ms and p99
  384 ms; 10/10 passed; aggregate CPU peak 651.73% (about 6.5 logical CPUs).
- Twenty-five concurrent sessions: 8.71 GiB peak memory on the restarted stack;
  response p95 1,110 ms and p99 4,815 ms; 0/25 passed; aggregate CPU peak
  1,214.41% (about 12.1 logical CPUs).
- Every active session also generated four real application 404 responses from
  the pricing/wallet routes. Expected unauthenticated bootstrap responses and
  cancelled navigation requests are reported separately.

Thirty percent above the representative 10-session memory peak is about
12.95 GiB. A 16 GiB host is therefore a hard minimum after allowing only a
small remainder for the OS, logging and deployment activity. The 10-session CPU
peak rules out treating four vCPUs as comfortable capacity.

## Per-service signals

At 10 concurrent sessions the highest observed CPU peaks were:

- application tracker: 112.55%;
- job finder gateway: 91.09%;
- job service: 86.01%;
- user profile service: 85.39%;
- user management gateway: 60.93%;
- authentication service: 60.69%;
- reporting service: 43.28%.

ClamAV was the largest idle container at about 0.94 GiB. Several Spring
services each held roughly 0.42–0.52 GiB at idle. The aggregate fixed floor,
rather than one leak, is the dominant memory cost of the current microservice
shape. Application tracker, job service, user profile, job finder and user
management are the first candidates for independent CPU scaling. The failed
job-details step at 25 sessions must be traced through job finder/job service
before a higher capacity claim is made.

## Current official prices

Pricing was retrieved on 2026-08-10 from the AWS Price List Bulk API for
`eu-west-2` (EU London), Linux/x86, shared tenancy, On-Demand, 730 hours/month.
London is used because the repository's SES configuration already names
`eu-west-2`; a compute-region architecture decision is still required.

Official sources:

- [AWS Price List method](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/finding-prices-in-service-price-list-files.html)
- [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [ECS pricing](https://aws.amazon.com/ecs/pricing/)
- [Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [EKS pricing](https://aws.amazon.com/eks/pricing/)
- [Lambda pricing](https://aws.amazon.com/lambda/pricing/)

| Item | Official rate | Calculated 730-hour month |
|---|---:|---:|
| EC2 `t3.xlarge`, 4 vCPU / 16 GiB | $0.1888/hour | $137.82 |
| EC2 `r7i.xlarge`, 4 vCPU / 32 GiB | $0.3108/hour | $226.88 |
| EC2 `m7i.2xlarge`, 8 vCPU / 32 GiB | $0.4662/hour | $340.33 |
| Fargate Linux/x86 vCPU | $0.04656/vCPU-hour | — |
| Fargate Linux/x86 memory | $0.00511/GB-hour | — |
| EKS standard-support control plane | $0.10/cluster-hour | $73.00 |
| Lambda x86 tier-one duration | $0.0000166667/GB-second | — |

All prices are USD, exclude tax and discounts, and exclude EBS, RDS, load
balancing, NAT, public IPv4, DNS, logs, backups and data transfer.

## Option comparison

| Approach | Calculated compute floor | Scaling and fit | Beta conclusion |
|---|---:|---|---|
| Plain EC2/Docker, `t3.xlarge` | $137.82/month | Fits the memory floor narrowly; four burstable vCPUs do not cover the measured 10-session peak; manual deployment/recovery. | Cheapest private-beta experiment only, capped near the successful five-session point with strict alarms. |
| ECS on EC2, `m7i.2xlarge` | $340.33/month | Eight vCPUs and 32 GiB; ECS orchestration has no extra charge; services can later be split across nodes. | Recommended first public-beta compute shape, still single-node and not HA. |
| Two ECS/EC2 `m7i.2xlarge` nodes | $680.65/month | Creates placement/failure headroom, but the application has not been benchmarked across nodes and databases still need an HA design. | Candidate after the single-node beta, not a measured requirement. |
| ECS Fargate, theoretically packed 8 vCPU / 16 GB | $331.60/month | Similar price to one `m7i.2xlarge`, but only if the services are packed into one task, losing independent scaling and failure isolation. | Poor fit for the existing service topology. |
| ECS Fargate, 36-task absolute minimum 0.25 vCPU / 0.5 GB each | $373.04/month | This is only a mathematical lower bound (9 vCPU/18 GB); several measured services need more than the minimum memory/CPU task shape. Actual cost must be higher. | Revisit only after per-service right-sizing and consolidation. |
| EKS with one `m7i.2xlarge` node | $413.33/month | Same worker limitation plus $73/month control-plane fee and Kubernetes operational work. | No evidence that beta needs the added complexity. |
| Lambda | About $459.90/month for a purely hypothetical continuously allocated 10.5 GB before requests | Current long-running Spring services, PostgreSQL and ClamAV do not map to short-lived stateless functions; a rewrite would be required. | Not credible for this system. |

The Fargate and Lambda figures are calculated comparison bounds, not proposed
deployments. They intentionally expose the fixed-cost penalty of many small,
always-on processes.

## Capacity model and scaling gates

| Environment | Resource model | Evidence boundary |
|---|---|---|
| Minimum/private test | 4 vCPU, 16 GiB | Calculated minimum; use only with low concurrency and no availability claim. |
| Comfortable development | 16 logical CPUs, 32 GiB | Matches the measured host and supports full-stack work. |
| Initial public beta | 8 vCPU, 32 GiB | Calculated from the measured memory floor and 10-session CPU peak; cap/alert around 10 concurrent active DISCOVER sessions. |
| Higher concurrency | Multiple nodes or independently scaled hot services | Projected architecture only. No supported user number until the 25-session job-details failure is fixed and rerun. |

Required next gates are: remove the payment-route 404s, trace the 25-session
job-details bottleneck, add service/request correlation for the hot path, define
production task CPU/memory reservations, separate production databases from
the measured local stack, and rerun 10/15/20/25 sessions on the selected AWS
shape. Only then should Savings Plans, Multi-AZ or a Fargate break-even point be
modelled as a commitment.

## Validation status

No workload in this evidence set ran on AWS, and no cloud resources were
created. The recommendation is a calculated starting shape, not a deployment
record or availability claim. See `real-world-validation-costs-2026-08-10.md`
for the paid-call boundary and the public beta-readiness page for the explicit
go/no-go conditions.
