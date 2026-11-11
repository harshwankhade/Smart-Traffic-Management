"""Audit the latest Phase 4 test and remove only its newly-created Kafka service role.

Run only after the runner's Terraform destroy. Exact run names and VPC IDs come from the
runner evidence; no unrelated names, IDs or dates are inferred.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import time

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/phase-4-cloud.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove-new-service-role", action="store_true")
    args = parser.parse_args()
    cloud = json.loads(EVIDENCE.read_text())
    project = cloud["run_name"]
    vpc = cloud.get("outputs", {}).get("vpc_id")
    if not vpc:
        # A failed initial apply may not reach the runner's output-capture step. Recover the
        # exact ID from that apply's own log section, never from a broad account inventory.
        log = (ROOT / ".data/phase4-cloud/terraform.log").read_text()
        current_apply = log.rsplit("COMMAND apply -input=false -no-color", 1)[-1]
        ids = re.findall(r"vpc-[0-9a-f]+", current_apply)
        vpc = ids[0] if ids else None
    if not project.startswith("stp4-") or not vpc:
        raise RuntimeError("Cleanup evidence lacks an exact Phase 4 run name or VPC ID")
    session = boto3.Session(profile_name="smarttraffic-sdk", region_name="ap-south-1")
    result = {"run": project, "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    result["emr_clusters"] = [c for page in session.client("emr").get_paginator("list_clusters").paginate(
        ClusterStates=["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING", "TERMINATING"])
        for c in page.get("Clusters", []) if c["Name"] == project + "-emr"]
    kafka = session.client("kafka")
    result["clusters"] = [c for page in kafka.get_paginator("list_clusters_v2").paginate() for c in page.get("ClusterInfoList", []) if c["ClusterName"].startswith(project)]
    result["configurations"] = [c for page in kafka.get_paginator("list_configurations").paginate() for c in page.get("Configurations", []) if c["Name"].startswith(project)]
    result["applications"] = [a for page in session.client("kinesisanalyticsv2").get_paginator("list_applications").paginate() for a in page.get("ApplicationSummaries", []) if a["ApplicationName"].startswith(project)]
    result["buckets"] = [b for b in session.client("s3").list_buckets().get("Buckets", []) if b["Name"].startswith(project)]
    ec2 = session.client("ec2")
    result["vpcs"] = ec2.describe_vpcs(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["Vpcs"]
    result["security_groups"] = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"]
    result["network_interfaces"] = ec2.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["NetworkInterfaces"]
    result["log_groups"] = session.client("logs").describe_log_groups(logGroupNamePrefix="/smarttraffic/" + project).get("logGroups", [])
    rds = session.client("rds")
    result["database_instances"] = [d["DBInstanceIdentifier"] for page in rds.get_paginator("describe_db_instances").paginate() for d in page["DBInstances"] if d["DBInstanceIdentifier"].startswith(project)]
    result["database_subnet_groups"] = [d["DBSubnetGroupName"] for page in rds.get_paginator("describe_db_subnet_groups").paginate() for d in page["DBSubnetGroups"] if d["DBSubnetGroupName"].startswith(project)]
    result["database_parameter_groups"] = [d["DBParameterGroupName"] for page in rds.get_paginator("describe_db_parameter_groups").paginate() for d in page["DBParameterGroups"] if d["DBParameterGroupName"].startswith(project)]
    iam = session.client("iam")
    result["project_roles"] = [r["RoleName"] for page in iam.get_paginator("list_roles").paginate() for r in page["Roles"] if r["RoleName"].startswith(project)]
    result["project_policies"] = [p["PolicyName"] for page in iam.get_paginator("list_policies").paginate(Scope="Local") for p in page["Policies"] if p["PolicyName"].startswith(project)]
    try:
        role = iam.get_role(RoleName="AWSServiceRoleForKafka")["Role"]
        role_existed = cloud.get("kafka_service_role_before", {}).get("present", True)
        if args.remove_new_service_role and not role_existed:
            if role["Path"] != "/aws-service-role/kafka.amazonaws.com/":
                raise RuntimeError("Kafka service role path does not match the service-linked role")
            if result["clusters"]:
                raise RuntimeError("Test cluster still exists; service-role cleanup cannot start")
            # AWS independently refuses deletion if the service role is still needed by any cluster.
            task = iam.delete_service_linked_role(RoleName="AWSServiceRoleForKafka")["DeletionTaskId"]
            deadline = time.monotonic() + 300
            while True:
                status = iam.get_service_linked_role_deletion_status(DeletionTaskId=task)
                if status["Status"] == "SUCCEEDED":
                    result["new_kafka_service_role_removed"] = True
                    break
                if status["Status"] == "FAILED" or time.monotonic() > deadline:
                    raise RuntimeError("Service-role cleanup not complete: " + json.dumps(status, default=str))
                time.sleep(5)
        elif role_existed:
            result["preexisting_kafka_service_role_preserved"] = True
            result["new_kafka_service_role_removed"] = True
        else:
            result["new_kafka_service_role_remaining"] = True
    except iam.exceptions.NoSuchEntityException:
        result["new_kafka_service_role_removed"] = True
    leftovers = {k: v for k, v in result.items() if isinstance(v, list) and v}
    result["all_run_resources_removed"] = not leftovers and result.get("new_kafka_service_role_removed", False)
    path = ROOT / "docs/evidence/phase-4-cleanup.json"
    path.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps(result, indent=2, default=str))
    if not result["all_run_resources_removed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
