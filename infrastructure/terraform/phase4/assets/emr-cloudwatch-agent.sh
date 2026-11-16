#!/bin/bash
set -euo pipefail

log_group="$1"
yum install -y amazon-cloudwatch-agent
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {"file_path": "/var/log/hadoop-yarn/containers/*/*/stdout", "log_group_name": "${log_group}", "log_stream_name": "{instance_id}/yarn-stdout"},
          {"file_path": "/var/log/hadoop-yarn/containers/*/*/stderr", "log_group_name": "${log_group}", "log_stream_name": "{instance_id}/yarn-stderr"}
        ]
      }
    }
  }
}
EOF
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s
