#!/usr/bin/env bash
# 等待 Slurm 作业到达终态。用法: wait_slurm_job.sh <job_id> [interval_s=30] [timeout_s=86400]
# 退出码: 0=COMPLETED, 1=FAILED/CANCELLED/TIMEOUT/其他终态, 2=超时仍在跑, 3=查无此作业
set -u
JOB="${1:?usage: wait_slurm_job.sh <job_id> [interval_s] [timeout_s]}"
INTERVAL="${2:-30}"
TIMEOUT="${3:-86400}"
START=$(date +%s)

while true; do
  LINE=$(squeue -j "$JOB" -h -o '%i %T' 2>/dev/null || true)
  if [ -n "$LINE" ]; then
    echo "$(date +%H:%M:%S) job $JOB in queue: $LINE"
  else
    ACCT=$(sacct -j "$JOB" -X -P -n --format=JobID,State,ExitCode 2>/dev/null || true)
    if [ -z "$ACCT" ]; then
      echo "$(date +%H:%M:%S) job $JOB not in squeue and unknown to sacct (never submitted?)"
      exit 3
    fi
    STATE=$(echo "$ACCT" | head -1 | cut -d'|' -f2)
    EXITC=$(echo "$ACCT" | head -1 | cut -d'|' -f3)
    echo "$(date +%H:%M:%S) job $JOB terminal state: $STATE exit=$EXITC"
    [ "$STATE" = "COMPLETED" ] && exit 0
    exit 1
  fi
  NOW=$(date +%s)
  if [ $((NOW - START)) -ge "$TIMEOUT" ]; then
    echo "timeout after ${TIMEOUT}s, job still active"
    exit 2
  fi
  sleep "$INTERVAL"
done
