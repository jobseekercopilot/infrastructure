# Public-beta AWS cost controls

The planning baseline is approximately **USD 560/month** in `eu-west-2` before
credits and before material traffic growth. Re-price it in the AWS Pricing
Calculator immediately before launch; this is an engineering estimate, not a
quote.

These hosting costs are not the customer-price catalog. For public-beta release
planning, the dated 11 August £5/£10/£20 subscription hypotheses are historical
and superseded by non-renewing document-credit packs: 10/£7.99, 25/£16.99 and
60/£34.99, with two free credits. Checkout is implemented but remains
release-gated/disabled and no live charge is claimed by this plan.

| Cost group | Planning range/month | Main variance |
|---|---:|---|
| one `m7i.2xlarge`, 100 GiB gp3 | $340–390 | hours and London price |
| `db.t4g.medium`, 50 GiB gp3, backups/PI | $80–115 | storage, I/O, retained backups |
| one NAT Gateway and ALB | $55–85 | processed GB and LCUs |
| WAF, Route 53, KMS, S3, ECR, logs, SES | $45–85 | requests, logs, scans, document volume |
| expected planning total | **about $560** | traffic and retained data |

The retained bootstrap `MonthlyCostAlertBudget` owns the **USD 750 alert
budget**; Terraform must consume the identical `MonthlyAlertBudgetUsd` output
as `foundation_monthly_alert_budget_usd` and `monthly_budget_usd`. It is not a
hard cap. Actual alerts are sent at 50%, 80% and 100%, forecast alerts at 80%,
and a daily Cost Anomaly Detection subscription triggers from a $20 absolute impact.
Email subscriptions must be confirmed. Cost-allocation tags may take time to
activate, so the billing console must confirm that `CostCentre=public-beta` is
an active cost-allocation tag before relying on the filtered budget.

Harder engineering bounds are separate:

- lean ASG min/desired/max are all one; ECS managed capacity cannot add a
  second node, and its `0/100` host refresh cannot add temporary capacity;
- the bootstrap Apply policy also caps ASG create/update at one node and pins
  a numeric launch-template version; HA requires a separately reviewed
  bootstrap/IAM and cost-ceiling change before Terraform can request it;
- lean service maximum is one and deployment is stop-first;
- RDS maximum storage is 200 GiB and backup retention is 35 days;
- one reviewed `securityLogRetentionDays` value applies to both CloudWatch and
  access-log S3 retention (30 days in the lean baseline);
- external providers need manifest request and cost ceilings;
- Google remains disabled without a named GCP project, exact billable quota IDs
  and daily limits, a true external verification record, separate GCP alerts at
  50/75/90/100%, and an owned emergency-disable runbook; and
- public traffic can be stopped by returning the ALB to fixed `503`, then
  scaling application services to zero through the protected release path.

AWS Budgets does not automatically stop resources. An operator must respond to
alerts using the incident/maintenance steps in the deployment runbook. A change
to HA, instance shape, NAT count, retention, WAF rules or traffic assumptions
requires an updated calculator export and a newly approved alert ceiling.

Google Maps is a specialist API outside AWS hosting costs. Google documents its
startup-program Maps benefit as a **separate application**, so no expected
benefit is included in the AWS estimate and Maps stays disabled until the
separate application, quota and billing controls are approved.
GCP budget alerts are also notification controls rather than a hard cap; the
exact service quotas and protected disable switch are the enforcement path.
