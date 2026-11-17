#!/usr/bin/env bash
# Run simulator and training jobs on an AWS spot instance instead of this Mac.
#
#   tools/aws/cloud.sh setup                      # once: S3 bucket + instance role (needs `aws configure` first)
#   tools/aws/cloud.sh run [opts] -- COMMAND      # ship code + data, launch an instance, run COMMAND
#   tools/aws/cloud.sh status [RUN_ID]            # running instances; with RUN_ID, its state and log tail
#   tools/aws/cloud.sh log RUN_ID                 # the whole log so far
#   tools/aws/cloud.sh fetch RUN_ID               # download out/ to tools/.cache/aws-runs/RUN_ID
#   tools/aws/cloud.sh stop [RUN_ID]              # terminate one run's instance, or all of them
#
# run options:
#   --type T       instance type (default c7i.8xlarge: 32 vCPU, 64 GB; ~$0.5/h spot, ~$1.4/h on demand)
#   --hours H      hard limit; the instance shuts itself down (and is deleted) after H hours (default 8)
#   --on-demand    don't use spot (costs ~3x more, but AWS can't reclaim it mid-run)
#   --data FILE    a data file the command reads, given relative to the repo root; repeatable. Uploaded once
#                  and reused by later runs while its size is unchanged
#
# COMMAND runs from the repo root on the instance with the venv active. Write results under out/, e.g.
#   tools/aws/cloud.sh run --data tools/.cache/replay-training.json -- \
#     python tools/train_policy.py tools/.cache/replay-training.json --hidden 32 -o out/replay-h32.json
# The log (out/run.log) is copied to S3 every minute; when COMMAND exits, out/ is uploaded and the instance
# terminates itself. The simulator's card and deck files in tools/.cache are always sent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CONFIG="$HERE/config.env"
ROLE=ygo-train-ec2
ALWAYS_DATA="tools/.cache/cardinfo_misc.json tools/.cache/fl_list_goat.json tools/.cache/fl_decks_goat.json tools/.cache/decks_goat.json"

die() { echo "error: $*" >&2; exit 1; }
need_config() { [ -f "$CONFIG" ] || die "run '$0 setup' first"; . "$CONFIG"; export AWS_REGION="$REGION"; }

cmd_setup() {
  command -v aws >/dev/null || die "install the AWS CLI: brew install awscli"
  local account region
  account=$(aws sts get-caller-identity --query Account --output text) || die "no AWS credentials: run 'aws configure'"
  region="${AWS_REGION:-$(aws configure get region || true)}"; region="${region:-us-east-1}"
  local bucket="ygo-train-$account-$region"
  echo "account $account, region $region, bucket $bucket"

  if ! aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    if [ "$region" = us-east-1 ]; then aws s3api create-bucket --bucket "$bucket" --region "$region" >/dev/null
    else aws s3api create-bucket --bucket "$bucket" --region "$region" --create-bucket-configuration LocationConstraint="$region" >/dev/null; fi
    aws s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    echo "created bucket"
  fi

  local fresh=0
  if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
      '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    fresh=1
  fi
  # The instance can read and write this one bucket and nothing else.
  aws iam put-role-policy --role-name "$ROLE" --policy-name bucket-access --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\"],\"Resource\":\"arn:aws:s3:::$bucket\"},
    {\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\"],\"Resource\":\"arn:aws:s3:::$bucket/*\"}]}"
  if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
    fresh=1
  fi
  [ $fresh = 1 ] && { echo "created instance role $ROLE; waiting for it to propagate"; sleep 15; }

  printf 'REGION=%s\nBUCKET=%s\n' "$region" "$bucket" > "$CONFIG"
  echo "wrote $CONFIG"

  # New accounts often have small vCPU limits, which make launches fail with VcpuLimitExceeded/MaxSpotInstanceCountExceeded.
  local spot od
  spot=$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-34B43A08 --query Quota.Value --output text 2>/dev/null || echo "?")
  od=$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A --query Quota.Value --output text 2>/dev/null || echo "?")
  echo "vCPU limits in $region: spot $spot, on demand $od (c7i.8xlarge needs 32)."
  echo "Raise them under Service Quotas > EC2 if they're lower; increases are usually approved within a day."
}

# Upload FILE (relative to ROOT) to s3://BUCKET/data/FILE unless an object of the same size is already there.
upload_data() {
  local f="$1" local_size remote_size
  [ -f "$ROOT/$f" ] || die "no such data file: $f"
  local_size=$(stat -f %z "$ROOT/$f")
  remote_size=$(aws s3api head-object --bucket "$BUCKET" --key "data/$f" --query ContentLength --output text 2>/dev/null || echo none)
  if [ "$local_size" != "$remote_size" ]; then
    echo "uploading $f ($((local_size / 1048576)) MB)"
    aws s3 cp "$ROOT/$f" "s3://$BUCKET/data/$f" --only-show-errors
  fi
}

cmd_run() {
  need_config
  local type=c7i.8xlarge hours=8 market=spot data=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --type) type="$2"; shift 2 ;;
      --hours) hours="$2"; shift 2 ;;
      --on-demand) market=ondemand; shift ;;
      --data) data="$data ${2#./}"; shift 2 ;;
      --) shift; break ;;
      *) die "unknown option $1 (put the command after --)" ;;
    esac
  done
  [ $# -gt 0 ] || die "no command given after --"
  local cmd="$*"
  local run_id; run_id="$(date +%Y%m%d-%H%M%S)"
  local s3="s3://$BUCKET/runs/$run_id"

  tmp=$(mktemp -d)  # global: the EXIT trap runs after this function returns
  trap 'rm -rf "$tmp"' EXIT
  # Code only: the cache, the replay key, and local config stay here.
  (cd "$ROOT" && COPYFILE_DISABLE=1 tar czf "$tmp/code.tgz" --exclude 'tools/.cache' --exclude '__pycache__' \
     --exclude 'tools/aws/config.env' tools models)
  aws s3 cp "$tmp/code.tgz" "$s3/code.tgz" --only-show-errors
  printf '%s\n' "$cmd" | aws s3 cp - "$s3/command.txt" --only-show-errors
  local f; for f in $ALWAYS_DATA $data; do upload_data "$f"; done

  local arch=amd64
  echo "$type" | grep -Eq '^[a-z]+[0-9]+g' && arch=arm64
  local ami; ami=$(aws ssm get-parameter --name "/aws/service/canonical/ubuntu/server/24.04/stable/current/$arch/hvm/ebs-gp3/ami-id" \
    --query Parameter.Value --output text)

  local cmd_b64; cmd_b64=$(printf '%s\n' "$cmd" | base64 | tr -d '\n')
  cat > "$tmp/user-data.sh" <<EOF
#!/bin/bash
# Watchdog first, so nothing below can keep the instance alive past the limit.
shutdown -h +$((hours * 60))
export HOME=/root PATH=/snap/bin:/usr/local/bin:\$PATH
exec > /var/log/ygo-boot.log 2>&1
set -euxo pipefail
S3=$s3
finish() { aws s3 cp /var/log/ygo-boot.log \$S3/boot.log || true; shutdown -h now; }
trap finish EXIT
snap install aws-cli --classic
echo setting-up | aws s3 cp - \$S3/status
mkdir -p /work && cd /work
aws s3 cp \$S3/code.tgz - | tar xz
for f in $ALWAYS_DATA $data; do mkdir -p "\$(dirname "\$f")"; aws s3 cp "s3://$BUCKET/data/\$f" "\$f" --only-show-errors; done
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
uv venv -p 3.14 .venv
VIRTUAL_ENV=/work/.venv uv pip install numpy==2.5.4
echo $cmd_b64 | base64 -d > cmd.sh
mkdir -p out
echo running | aws s3 cp - \$S3/status
set +e
( . .venv/bin/activate; bash cmd.sh ) > out/run.log 2>&1 &
pid=\$!
while kill -0 \$pid 2>/dev/null; do aws s3 cp out/run.log \$S3/out/run.log --only-show-errors; sleep 60; done
wait \$pid; rc=\$?
set -e
aws s3 sync out \$S3/out --only-show-errors
echo "exited \$rc" | aws s3 cp - \$S3/status
EOF

  local market_opt=()
  [ "$market" = spot ] && market_opt=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
  local iid
  iid=$(aws ec2 run-instances --image-id "$ami" --instance-type "$type" ${market_opt[@]+"${market_opt[@]}"} \
    --iam-instance-profile Name="$ROLE" --instance-initiated-shutdown-behavior terminate \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3,DeleteOnTermination=true}' \
    --user-data "file://$tmp/user-data.sh" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=ygo-train-$run_id},{Key=Project,Value=ygo-train},{Key=RunId,Value=$run_id}]" \
    --query 'Instances[0].InstanceId' --output text)
  echo "launched $iid ($type, $market, ${hours}h limit)"
  echo "run id: $run_id"
  echo "  $0 status $run_id     # state + log tail (log starts ~3 min after launch)"
  echo "  $0 fetch $run_id      # results, once it says 'exited 0'"
}

cmd_status() {
  need_config
  aws ec2 describe-instances --filters Name=tag:Project,Values=ygo-train Name=instance-state-name,Values=pending,running,shutting-down \
    --query 'Reservations[].Instances[].[Tags[?Key==`RunId`]|[0].Value,InstanceId,InstanceType,State.Name,LaunchTime]' --output table
  if [ $# -gt 0 ]; then
    echo "status: $(aws s3 cp "s3://$BUCKET/runs/$1/status" - 2>/dev/null || echo 'not started yet')"
    aws s3 cp "s3://$BUCKET/runs/$1/out/run.log" - 2>/dev/null | tail -20 || true
  fi
}

cmd_log() { need_config; aws s3 cp "s3://$BUCKET/runs/$1/out/run.log" -; }

cmd_fetch() {
  need_config
  local dest="$ROOT/tools/.cache/aws-runs/$1"
  aws s3 sync "s3://$BUCKET/runs/$1/out" "$dest" --only-show-errors
  aws s3 cp "s3://$BUCKET/runs/$1/boot.log" "$dest/boot.log" --only-show-errors 2>/dev/null || true
  echo "status: $(aws s3 cp "s3://$BUCKET/runs/$1/status" - 2>/dev/null)"
  ls -lh "$dest"
}

cmd_stop() {
  need_config
  local filters=(Name=tag:Project,Values=ygo-train Name=instance-state-name,Values=pending,running)
  [ $# -gt 0 ] && filters+=(Name=tag:RunId,Values="$1")
  local ids; ids=$(aws ec2 describe-instances --filters "${filters[@]}" --query 'Reservations[].Instances[].InstanceId' --output text)
  [ -n "$ids" ] || { echo "nothing running"; return; }
  aws ec2 terminate-instances --instance-ids $ids --query 'TerminatingInstances[].InstanceId' --output text
}

sub="${1:-}"; [ $# -gt 0 ] && shift
case "$sub" in
  setup|run|status|log|fetch|stop) "cmd_$sub" "$@" ;;
  *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
