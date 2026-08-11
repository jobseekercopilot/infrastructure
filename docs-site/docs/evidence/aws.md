# AWS capacity decision

Decision date: **11 August 2026**

Region/basis: **eu-west-2 (London), Linux/x86, On-Demand, 730 hours/month**

## Recommendation

Use ECS on one EC2 `m7i.2xlarge` (8 vCPU, 32 GiB) as the **minimum calculated**
bounded public-beta starting shape, initially capped around 15 active DISCOVER
journeys. Its compute-only price is **$340.33/month**.

| Stage | Candidate | Compute/month | Evidence |
| --- | --- | ---: | --- |
| Private experiment | `t3.xlarge`, 4 vCPU / 16 GiB | $137.82 | Calculated; burstable and narrow headroom |
| Bounded public beta | `m7i.2xlarge`, 8 vCPU / 32 GiB | $340.33 | Calculated from fresh local measurement |
| Availability/growth | two `m7i.2xlarge` nodes | $680.65 | Modelled only; not benchmarked |

!!! danger "Not AWS-tested"
    No AWS workload ran. No deployable credential/tooling path was available,
    no resource was created and AWS validation spend was $0. Local results are
    not labelled cloud measurements.

Compute is not the AWS bill. RDS, storage, load balancing, public IPv4,
NAT/data transfer, DNS, logs, backups, support and tax are excluded. See
`docs/aws-capacity-decision-2026-08-11.md` for the full evidence boundary and
activation gates.
