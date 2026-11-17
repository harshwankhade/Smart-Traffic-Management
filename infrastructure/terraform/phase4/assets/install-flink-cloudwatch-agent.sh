#!/bin/bash
set -euo pipefail

config_uri="$1"
config_path="/opt/aws/amazon-cloudwatch-agent/etc/phase9-flink-logs.json"

aws s3 cp "${config_uri}" "${config_path}"
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a append-config -m ec2 -s -c "file:${config_path}"
systemctl is-active --quiet amazon-cloudwatch-agent
