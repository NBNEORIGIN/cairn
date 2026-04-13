# Amazon SP-API Notifications — AWS Setup Guide

## Overview

Amazon SP-API can push real-time notifications when listings change via SQS queues.
This eliminates the need for polling and enables near-instant detection of content changes,
pricing updates, and listing suppressions.

**AWS Account:** NBNE (9150-7785-2106)
**Date:** 2026-04-13

## Architecture

```
Amazon SP-API → SQS Queue (per region) → Cairn Notification Processor (long-poll)
```

Three SQS queues, one per region, in geographically appropriate AWS regions:
- EU notifications: `eu-west-2` (London)
- NA notifications: `us-east-1` (Virginia)
- FE notifications: `ap-southeast-2` (Sydney)

## Step 1: Create IAM User

1. Go to AWS Console → IAM → Users → Create User
2. User name: `cairn-spapi-notifications`
3. Attach policy: `AmazonSQSFullAccess` (or create custom policy below)
4. Create access key → download credentials
5. Add to Hetzner `.env`:
   ```
   AWS_ACCESS_KEY_ID=AKIA...
   AWS_SECRET_ACCESS_KEY=...
   AWS_DEFAULT_REGION=eu-west-2
   ```

### Custom IAM Policy (recommended over full SQS access)

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CairnSQSAccess",
            "Effect": "Allow",
            "Action": [
                "sqs:CreateQueue",
                "sqs:DeleteQueue",
                "sqs:GetQueueAttributes",
                "sqs:GetQueueUrl",
                "sqs:SetQueueAttributes",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:SendMessage",
                "sqs:ListQueues"
            ],
            "Resource": "arn:aws:sqs:*:ACCOUNT_ID:cairn-spapi-*"
        }
    ]
}
```

Replace `ACCOUNT_ID` with the NBNE AWS account number (915077852106, no dashes).

## Step 2: Create IAM Role for Amazon SP-API

Amazon's notification service needs an IAM role to publish to your SQS queues.

1. Go to IAM → Roles → Create Role
2. Trusted entity: **AWS Service** → **Another AWS account**
3. Account ID: `437568002678` (Amazon's SP-API notification service)
4. External ID: leave blank (Amazon doesn't require one for notifications)
5. Role name: `cairn-spapi-notification-publisher`
6. Attach inline policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": "arn:aws:sqs:*:ACCOUNT_ID:cairn-spapi-*"
        }
    ]
}
```

7. Note the role ARN: `arn:aws:iam::ACCOUNT_ID:role/cairn-spapi-notification-publisher`
8. Add to `.env`:
   ```
   AWS_SPAPI_SQS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/cairn-spapi-notification-publisher
   ```

## Step 3: Create SQS Queues

Create three queues via AWS Console or CLI:

```bash
# EU queue (London)
aws sqs create-queue \
  --queue-name cairn-spapi-notifications-eu \
  --region eu-west-2 \
  --attributes '{
    "VisibilityTimeout": "300",
    "MessageRetentionPeriod": "1209600",
    "ReceiveMessageWaitTimeSeconds": "20"
  }'

# NA queue (Virginia)
aws sqs create-queue \
  --queue-name cairn-spapi-notifications-na \
  --region us-east-1 \
  --attributes '{
    "VisibilityTimeout": "300",
    "MessageRetentionPeriod": "1209600",
    "ReceiveMessageWaitTimeSeconds": "20"
  }'

# FE queue (Sydney)
aws sqs create-queue \
  --queue-name cairn-spapi-notifications-fe \
  --region ap-southeast-2 \
  --attributes '{
    "VisibilityTimeout": "300",
    "MessageRetentionPeriod": "1209600",
    "ReceiveMessageWaitTimeSeconds": "20"
  }'
```

Settings:
- **VisibilityTimeout**: 300s (5min) — time to process before re-delivery
- **MessageRetentionPeriod**: 1209600s (14 days) — max retention
- **ReceiveMessageWaitTimeSeconds**: 20s — long-poll for efficiency

### Set Queue Policy

Each queue needs a policy allowing Amazon's role to send messages:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowSPAPINotifications",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::ACCOUNT_ID:role/cairn-spapi-notification-publisher"
            },
            "Action": "sqs:SendMessage",
            "Resource": "QUEUE_ARN"
        }
    ]
}
```

Apply via:
```bash
aws sqs set-queue-attributes \
  --queue-url QUEUE_URL \
  --attributes '{"Policy": "POLICY_JSON"}'
```

## Step 4: Add Queue URLs to .env

```
AWS_SQS_QUEUE_URL_EU=https://sqs.eu-west-2.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-eu
AWS_SQS_QUEUE_URL_NA=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-na
AWS_SQS_QUEUE_URL_FE=https://sqs.ap-southeast-2.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-fe
```

## Step 5: Register SP-API Notification Subscriptions

Use the Cairn API endpoints:

```bash
# Create destination (one per queue)
POST /ami/notifications/destinations
{
    "region": "EU",
    "queue_url": "https://sqs.eu-west-2.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-eu",
    "role_arn": "arn:aws:iam::ACCOUNT_ID:role/cairn-spapi-notification-publisher"
}

# Subscribe to notification types
POST /ami/notifications/subscriptions
{
    "region": "EU",
    "notification_type": "LISTINGS_ITEM_STATUS_CHANGE"
}
```

Supported notification types for listings:
- `LISTINGS_ITEM_STATUS_CHANGE` — listing status changes (active, inactive, suppressed)
- `LISTINGS_ITEM_ISSUES_CHANGE` — quality/compliance issues change
- `LISTINGS_ITEM_MFN_QUANTITY_CHANGE` — MFN inventory quantity changes

## Step 6: Verify

1. Send a test message via AWS Console → SQS → Send Message
2. Check Cairn logs for received notification
3. Trigger a listing change in Seller Central and verify notification arrives

## Environment Variables Summary

```
# IAM credentials
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-west-2

# SQS Role ARN (for Amazon to publish)
AWS_SPAPI_SQS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/cairn-spapi-notification-publisher

# Queue URLs
AWS_SQS_QUEUE_URL_EU=https://sqs.eu-west-2.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-eu
AWS_SQS_QUEUE_URL_NA=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-na
AWS_SQS_QUEUE_URL_FE=https://sqs.ap-southeast-2.amazonaws.com/ACCOUNT_ID/cairn-spapi-notifications-fe
```

## Cost Estimate

SQS pricing (all regions):
- First 1M requests/month: free
- Standard queue: $0.40 per 1M requests after free tier
- Expected volume: ~1,000 notifications/day across all regions
- **Monthly cost: $0.00** (well within free tier)
