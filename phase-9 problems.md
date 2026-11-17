# Phase 9 Problems — Native EMR CloudWatch Logs

## Current problem

Phase 9's centralized logging acceptance is incomplete for the EMR/Flink
runtime. EKS application logs and Lambda logs are available in CloudWatch, but
the EMR log group has no streams even though the native EMR CloudWatch logging
configuration is enabled and completed diagnostic steps have produced stdout
and stderr.

This is a runtime delivery problem, not a missing Terraform configuration.

## Scope and safety boundary

- Current authorized work is **Phase 9 Step 3 only**.
- Do not start final teardown or delete any further runtime resource without a
  new, separate explicit user approval.
- Cost cap stated by the user: **US$30**. Recheck current cost before any
  lengthy additional cloud work.
- Do not commit or push the local Terraform/documentation changes unless the
  user explicitly asks.
- The user explicitly approved the EMR-only replacement and the two IAM actions
  listed below. No wider IAM permission is approved.

## Current AWS resources

- Region: `ap-south-1`
- EKS cluster: `smarttraffic-phase8` (not part of this problem)
- Replacement EMR cluster: `j-0441383Q3WH0WUH5N4U`
- EMR cluster state when last checked: `WAITING`
- EMR release: `emr-7.14.0`
- EMR applications: `Flink`, `AmazonCloudWatchAgent`
- EMR log group: `/smarttraffic/smarttraffic-phase8-emr/emr`
- Configured stream prefix: `phase9`
- S3 EMR log URI remains:
  `s3n://smarttraffic-phase8-kafka-20261116053700312600000001/emr-logs/`

The configured native monitoring object returned by `aws emr describe-cluster`
is:

```json
{
  "CloudWatchLogConfiguration": {
    "Enabled": true,
    "LogGroupName": "/smarttraffic/smarttraffic-phase8-emr/emr",
    "LogStreamNamePrefix": "phase9",
    "LogTypes": {
      "STEP_LOGS": ["STDOUT", "STDERR"],
      "SPARK_DRIVER": ["STDOUT", "STDERR"],
      "SPARK_EXECUTOR": ["STDOUT", "STDERR"]
    }
  },
  "S3LoggingConfiguration": {}
}
```

## Evidence collected

1. The original Terraform `aws_emr_cluster` provider schema did not expose
   EMR's creation-time `MonitoringConfiguration`. A custom bootstrap CloudWatch
   agent was therefore tried first, but it never created a stream.
2. The original EMR worker (`j-037818516JCX5TXUWKV`) was explicitly approved
   for EMR-only replacement and terminated.
3. Terraform now owns an `aws_cloudformation_stack.congestion` resource. Its
   `AWS::EMR::Cluster` template enables native monitoring, retains the same
   `m5.xlarge` single worker, private subnet, security groups, instance profile,
   service role, log group and S3 archive location.
4. The replacement completed and reached `WAITING`.
5. A harmless `AddJobFlowSteps` diagnostic was submitted and completed:
   - `s-0982633218BKURLUKBJV`
   - command wrote distinct text to both stdout and stderr.
6. `aws logs describe-log-streams` for the configured log group returned zero
   streams after repeated checks.
7. The EMR EC2 role is `smarttraffic-phase8-emr-ec2`. It already had the
   stream-write permissions and `logs:DescribeLogGroups`.
8. The user then explicitly approved, and Terraform applied, exactly these
   additional permissions:
   - `logs:CreateLogGroup` on `*`
   - `logs:PutRetentionPolicy` on
     `arn:aws:logs:ap-south-1:520646131316:log-group:/smarttraffic/smarttraffic-phase8-emr/emr`
9. A second harmless diagnostic completed after that policy update:
   - `s-01633463RGHK5P1E1EU`
   - its stdout/stderr include the suffix `-after-iam`.
10. The log group still had zero streams after the post-IAM delivery checks.

## Files changed locally for this approach

- `infrastructure/terraform/phase4/main.tf`
  - Replaced the provider-managed EMR cluster declaration with a
    Terraform-managed CloudFormation stack containing `AWS::EMR::Cluster` and
    `MonitoringConfiguration`.
  - Added only the approved native-agent IAM actions described above.
- `infrastructure/terraform/phase4/outputs.tf`
  - Reads the EMR cluster ID/name from the CloudFormation stack outputs.
- `infrastructure/terraform/phase4/tests/foundation.tftest.hcl`
  - Tests the native template's release, applications, single worker and log
    types.
- `.tmp-phase9-native-cloudwatch-step.json`
  - Temporary harmless diagnostic step input; do not treat it as production
    configuration.

Verification already run after the Terraform edits:

```powershell
terraform -chdir=infrastructure/terraform/phase4 validate
terraform -chdir=infrastructure/terraform/phase4 test
```

Both passed; Terraform test result was `2 passed, 0 failed`.

## Important constraints and likely next investigation

AWS documents native EMR CloudWatch logging as a creation-time feature for EMR
7.11+ that requires `AmazonCloudWatchAgent`, a monitoring configuration, IAM
permissions and, for a private subnet, working CloudWatch Logs connectivity.
The first three are now observed on the replacement. The remaining likely
cause is the private-network path to the CloudWatch Logs endpoint, or a
native-agent/service-side authorization detail that CloudWatch does not expose
in the empty group.

Before changing resources, gather read-only evidence:

```powershell
$env:AWS_PROFILE = 'smarttraffic-sdk'
aws emr describe-cluster --cluster-id j-0441383Q3WH0WUH5N4U --region ap-south-1
aws logs describe-log-streams --log-group-name /smarttraffic/smarttraffic-phase8-emr/emr --region ap-south-1
aws ec2 describe-vpc-endpoints --region ap-south-1 --filters Name=vpc-id,Values=vpc-0ebce57fa85c4808f
```

In particular, inspect whether the private EMR subnet has a usable NAT route
or an Interface VPC endpoint for `com.amazonaws.ap-south-1.logs`, including
security-group ingress on TCP 443. Do not create an endpoint, change routing,
or broaden IAM without a new user approval and a cost/plan review.

Also inspect CloudFormation stack events before retrying anything:

```powershell
aws cloudformation describe-stack-events `
  --stack-name smarttraffic-phase8-emr-native-cloudwatch `
  --region ap-south-1
```

## Resolution update — CloudWatch Logs endpoint added

The network diagnosis was confirmed. The EMR primary security group allowed
TCP 443 only to the S3 prefix list, while the VPC had no CloudWatch Logs
interface endpoint. The NAT route existed, but the security group prevented
the EMR worker from reaching CloudWatch Logs.

After an explicitly approved, reviewed Terraform plan, these four resources
were created without replacing EMR:

1. One `com.amazonaws.ap-south-1.logs` interface VPC endpoint in the EMR
   worker subnet (`vpce-0fa8ecc9d6fc96958`), with private DNS enabled.
2. One dedicated endpoint security group.
3. TCP 443 egress from EMR primary to that endpoint security group.
4. TCP 443 ingress on that endpoint security group from EMR primary.

A new post-endpoint step, `s-02783782K9XRLQZKH2KL`, completed and produced
both native streams:

- `phase9/steps/s-02783782K9XRLQZKH2KL/stdout` contains
  `phase9-native-cloudwatch-stdout-after-endpoint`.
- `phase9/steps/s-02783782K9XRLQZKH2KL/stderr` contains
  `phase9-native-cloudwatch-stderr-after-endpoint` and a zero exit status.

This proves native EMR step-log delivery. Earlier completed diagnostics also
appeared after the endpoint was available, confirming that the absence of
CloudWatch connectivity—not the EMR monitoring configuration—was the blocker.

### Remaining acceptance limitation

This evidence proves native **step** logging only. Native EMR logging documents
step and Spark driver/executor streams; it does not by itself prove that the
Flink/YARN application container logs required for all-eight-runtime
observability are available. Inspect a real Flink job's emitted streams next.
If those are absent, propose a separately approved Terraform-owned CloudWatch
Agent file collector for verified `/mnt/var/log` Flink/YARN paths. Do not
claim complete EMR/Flink log coverage until that check passes.

## Commands used for the completed diagnostics

```powershell
$env:AWS_PROFILE = 'smarttraffic-sdk'
aws emr describe-step --cluster-id j-0441383Q3WH0WUH5N4U `
  --step-id s-01633463RGHK5P1E1EU --region ap-south-1
aws logs describe-log-streams `
  --log-group-name /smarttraffic/smarttraffic-phase8-emr/emr `
  --order-by LastEventTime --descending --region ap-south-1
```

Do not place AWS access keys, credential-process output, or other secrets in
this document.
