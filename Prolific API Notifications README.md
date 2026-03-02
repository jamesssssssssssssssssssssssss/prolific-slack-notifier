# Prolific → Slack Study Notifier

Polls your Prolific account every few minutes and sends a Slack notification whenever a study goes **ACTIVE** (live to participants).

## Setup (5 minutes)

### 1. Create a Slack Incoming Webhook

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it something like "Prolific Notifier", pick your workspace
3. Left sidebar → **Incoming Webhooks** → Toggle **ON**
4. Click **Add New Webhook to Workspace** → Pick your channel (e.g. `#prolific-alerts`)
5. Copy the webhook URL

### 2. Get Your Prolific API Token

1. Go to [app.prolific.com](https://app.prolific.com) → **Settings** → **API tokens**
2. Create a new token and copy it

### 3. Configure the Script

Set environment variables (recommended):
```bash
export PROLIFIC_API_TOKEN="your_prolific_token_here"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
```

Or edit the values directly at the top of `prolific_slack_notifier.py`.

### 4. Test It

```bash
python3 prolific_slack_notifier.py
```

First run records current state without sending notifications (so you don't get spammed about existing active studies). Second run onward will notify about any *new* status changes to ACTIVE.

### 5. Set Up Cron (Every 2 Minutes)

```bash
crontab -e
```

Add this line:
```
*/2 * * * * PROLIFIC_API_TOKEN="your_token" SLACK_WEBHOOK_URL="your_webhook_url" /usr/bin/python3 /path/to/prolific_slack_notifier.py >> /var/log/prolific_notifier.log 2>&1
```

## Run 24/7 with cron-job.org (simplest, free)

This runs the notifier every 5 minutes in the cloud. No Mac, no server.

### 1. GitHub repo + secrets

- Push this project to a GitHub repo (include `.github/workflows/prolific-notifier.yml` and `Prolific Slack Notifier.py`).
- In the repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
  - `PROLIFIC_API_TOKEN` = your Prolific API token  
  - `SLACK_WEBHOOK_URL` = your Slack webhook URL  

### 2. GitHub token for cron-job.org

- GitHub → **Settings** (your profile) → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
- Name it e.g. `cron-job-prolific`. Tick **repo** (if the repo is private) and **workflow**. Generate and copy the token.

### 3. cron-job.org

1. Sign up at **[cron-job.org](https://cron-job.org)** (free).
2. **Create cron job**:
   - **Title:** `Prolific notifier`
   - **Address (URL):**  
     `https://api.github.com/repos/jamesssssssssssssssssssssss/prolific-slack-notifier/actions/workflows/prolific-notifier.yml/dispatches`  
     *(Change the username/repo if yours is different.)*
   - **Schedule:** Every **5** **minutes**
   - **Request method:** **POST**
   - **Request headers:** Add these three (cron-job.org usually has an “Advanced” or “Headers” section):
     - `Authorization` = `Bearer PASTE_YOUR_GITHUB_TOKEN_HERE`
     - `Accept` = `application/vnd.github.v3+json`
     - `Content-Type` = `application/json`
   - **Request body:** `{"ref":"main"}`
3. **Save.** The job will trigger your GitHub workflow every 5 minutes.

Done. You can confirm in the repo’s **Actions** tab that runs appear every 5 minutes.

---

## How It Works

1. Fetches all studies from `GET /api/v1/studies/`
2. Compares each study's status against the last known status (stored in `.prolific_seen_studies.json`)
3. If a study transitions to `ACTIVE`, sends a rich Slack notification with study details + a button to view it
4. Saves updated state for the next run

## Customization

- **Notify on other statuses**: Edit `NOTIFY_STATUSES` in the script (e.g. add `"COMPLETED"`, `"AWAITING_REVIEW"`)
- **Change polling frequency**: Adjust the cron interval (`*/2` = every 2 min, `*/5` = every 5 min)
- **Multiple Slack channels**: Duplicate the `send_slack_message` call with different webhook URLs

## No Dependencies

Uses only Python standard library — no `pip install` needed. Runs on Python 3.10+.
