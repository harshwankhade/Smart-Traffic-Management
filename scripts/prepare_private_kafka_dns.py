"""Bound negative caching in the project-owned private Kafka hosted zone.

Terraform calls this when creating the zone because its provider does not expose
the default SOA's TTL. The default record remains owned by the hosted zone and
is removed with it. Without --apply this only displays the proposed change.
"""
import argparse
import json
import os
import boto3


def bounded_soa(record):
    updated = dict(record)
    updated['TTL'] = 30
    parts = record['ResourceRecords'][0]['Value'].split()
    if record['Type'] != 'SOA' or len(parts) != 7:
        raise ValueError('Expected one standard SOA record')
    parts[-1] = '30'
    updated['ResourceRecords'] = [{'Value': ' '.join(parts)}]
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zone-id', required=True)
    parser.add_argument('--expected-account-id')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    session = boto3.Session(profile_name=os.getenv('AWS_PROFILE'), region_name=os.getenv('AWS_REGION', 'ap-south-1'))
    account = session.client('sts').get_caller_identity()['Account']
    if args.expected_account_id and account != args.expected_account_id:
        raise RuntimeError('Selected account does not match the expected account')
    route53 = session.client('route53')
    zone = route53.get_hosted_zone(Id=args.zone_id)['HostedZone']
    if zone['Name'] != 'smarttraffic.internal.' or not zone['Config']['PrivateZone']:
        raise RuntimeError('Refusing to change a public or unrelated zone')
    tags = {t['Key']: t['Value'] for t in route53.list_tags_for_resource(ResourceType='hostedzone', ResourceId=args.zone_id)['ResourceTagSet']['Tags']}
    if tags.get('Project') != 'SmartTraffic' or tags.get('ManagedBy') != 'Terraform':
        raise RuntimeError('Private zone lacks project ownership tags')
    old = next(r for p in route53.get_paginator('list_resource_record_sets').paginate(HostedZoneId=args.zone_id) for r in p['ResourceRecordSets'] if r['Type'] == 'SOA')
    new = bounded_soa(old)
    print(json.dumps({'account': account, 'zone': zone['Name'], 'old_ttl': old['TTL'], 'new_ttl': new['TTL'], 'apply': args.apply}))
    if args.apply and new != old:
        route53.change_resource_record_sets(HostedZoneId=args.zone_id, ChangeBatch={'Comment': 'Bound Kafka private DNS negative caching', 'Changes': [{'Action': 'UPSERT', 'ResourceRecordSet': new}]})


if __name__ == '__main__':
    main()
