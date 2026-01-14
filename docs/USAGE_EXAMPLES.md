# Usage Examples

Real-world examples and common scenarios for using the GitLab Stale Branch Notifier.

## Table of Contents

- [Basic Usage](#basic-usage)
- [Testing and Validation](#testing-and-validation)
- [Automation](#automation)
- [Common Scenarios](#common-scenarios)
- [Advanced Usage](#advanced-usage)
- [Tips and Tricks](#tips-and-tricks)

## Basic Usage

### Running with Default Configuration

```bash
python stale_branch_notifier.py
```

This will:
1. Read `config.yaml` from the current directory
2. Connect to GitLab and scan configured projects
3. Find stale branches and merge requests
4. Send email notifications to developers

**Expected output:**
```
2024-01-14 10:00:00 - INFO - Connecting to GitLab...
2024-01-14 10:00:01 - INFO - Checking project: my-project (ID: 123)
2024-01-14 10:00:02 - INFO - Found 5 stale branches
2024-01-14 10:00:03 - INFO - Email sent successfully to alice@example.com
2024-01-14 10:00:04 - INFO - Email sent successfully to bob@example.com
2024-01-14 10:00:04 - INFO - ==================================================
2024-01-14 10:00:04 - INFO - Stale Branch/MR Notification Summary
2024-01-14 10:00:04 - INFO - ==================================================
2024-01-14 10:00:04 - INFO - Total stale branches found: 5
2024-01-14 10:00:04 - INFO - Total stale merge requests found: 2
2024-01-14 10:00:04 - INFO - Emails sent: 2
2024-01-14 10:00:04 - INFO - Emails failed: 0
2024-01-14 10:00:04 - INFO - Recipients: alice@example.com, bob@example.com
```

### Using Custom Configuration File

```bash
python stale_branch_notifier.py -c /path/to/custom-config.yaml
```

**Use cases:**
- Different configurations for different environments
- Testing with alternative settings
- Multiple GitLab instances

**Example:**
```bash
# Development environment
python stale_branch_notifier.py -c config.dev.yaml

# Production environment
python stale_branch_notifier.py -c config.prod.yaml

# Specific team/group
python stale_branch_notifier.py -c team-alpha-config.yaml
```

### Verbose Logging

```bash
python stale_branch_notifier.py -v
# or
python stale_branch_notifier.py --verbose
```

**When to use:**
- Debugging configuration issues
- Understanding notification routing decisions
- Troubleshooting email delivery

**Output includes:**
```
2024-01-14 10:00:00 - DEBUG - Skipping protected branch: main
2024-01-14 10:00:01 - DEBUG - Checking branch: feature/new-ui
2024-01-14 10:00:01 - DEBUG - Branch last commit: 2023-12-01 (44 days ago)
2024-01-14 10:00:01 - INFO - User alice@example.com is not active, using fallback email
2024-01-14 10:00:02 - DEBUG - Subject: [Action Required] 3 Stale Branch(es) Require Attention
```

## Testing and Validation

### Dry Run Mode

**Most important command for testing!**

```bash
python stale_branch_notifier.py --dry-run
```

**What it does:**
- ✅ Connects to GitLab
- ✅ Scans projects for stale items
- ✅ Determines who would receive emails
- ✅ Shows what would be sent
- ❌ Does NOT send actual emails

**Example output:**
```
2024-01-14 10:00:00 - INFO - Connecting to GitLab...
2024-01-14 10:00:02 - INFO - [DRY RUN] Would send email to: alice@example.com
2024-01-14 10:00:02 - INFO - [DRY RUN] Would send email to: bob@example.com
2024-01-14 10:00:02 - INFO - ==================================================
2024-01-14 10:00:02 - INFO - Total stale branches found: 7
2024-01-14 10:00:02 - INFO - Total stale merge requests found: 3
2024-01-14 10:00:02 - INFO - Emails sent: 2
```

### Combined Dry Run with Verbose

```bash
python stale_branch_notifier.py --dry-run -v
```

**Perfect for:**
- Initial setup verification
- Testing configuration changes
- Understanding why certain branches are/aren't flagged

**Detailed output:**
```
2024-01-14 10:00:00 - DEBUG - Skipping protected branch: main
2024-01-14 10:00:01 - DEBUG - Branch feature/auth-system is stale (45 days old)
2024-01-14 10:00:01 - DEBUG - Found MR !42 for branch feature/auth-system
2024-01-14 10:00:01 - DEBUG - MR assignee: alice@example.com (active)
2024-01-14 10:00:02 - INFO - [DRY RUN] Would send email to: alice@example.com
2024-01-14 10:00:02 - DEBUG - Subject: [Action Required] 1 Stale Merge Request(s) Require Attention
```

### Testing SMTP Configuration

Create a test script `test_smtp.py`:

```python
#!/usr/bin/env python3
import yaml
import smtplib

# Load your config
with open('config.yaml') as f:
    config = yaml.safe_load(f)

smtp_config = config['smtp']

try:
    with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
        if smtp_config.get('use_tls', True):
            server.starttls()
        if smtp_config.get('username') and smtp_config.get('password'):
            server.login(smtp_config['username'], smtp_config['password'])
        print("✅ SMTP connection successful!")
except Exception as e:
    print(f"❌ SMTP connection failed: {e}")
```

Run it:
```bash
python test_smtp.py
```

## Automation

### Cron Job (Linux/Mac)

**Weekly notifications** (Every Monday at 9 AM):

```bash
# Edit crontab
crontab -e

# Add this line:
0 9 * * 1 cd /path/to/repo-maintainer && /path/to/python stale_branch_notifier.py
```

**Daily notifications** (Every day at 10 AM):
```bash
0 10 * * * cd /path/to/repo-maintainer && /path/to/python stale_branch_notifier.py
```

**Bi-weekly notifications** (Every other Monday):
```bash
0 9 * * 1 [ $(expr $(date +\%W) \% 2) -eq 0 ] && cd /path/to/repo-maintainer && /path/to/python stale_branch_notifier.py
```

**With logging:**
```bash
0 9 * * 1 cd /path/to/repo-maintainer && /path/to/python stale_branch_notifier.py >> /var/log/stale-branch-notifier.log 2>&1
```

### GitLab CI/CD Pipeline

Create `.gitlab-ci.yml` in your repository:

```yaml
stale-branch-notification:
  image: python:3.9
  before_script:
    - pip install -r requirements.txt
  script:
    - python stale_branch_notifier.py
  only:
    - schedules
  variables:
    GITLAB_TOKEN: ${GITLAB_PRIVATE_TOKEN}
    SMTP_PASSWORD: ${SMTP_PASSWORD}
```

Then in GitLab:
1. Go to **CI/CD** → **Schedules**
2. Click **New schedule**
3. Set pattern: `0 9 * * 1` (weekly on Monday)
4. Add variables for secrets
5. Save

### GitHub Actions

Create `.github/workflows/stale-branches.yml`:

```yaml
name: Stale Branch Notification

on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday at 9 AM UTC
  workflow_dispatch:  # Allow manual trigger

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run notification script
        env:
          GITLAB_TOKEN: ${{ secrets.GITLAB_TOKEN }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
        run: python stale_branch_notifier.py
```

### Docker Container

**Dockerfile:**
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stale_branch_notifier.py .
COPY config.yaml .

CMD ["python", "stale_branch_notifier.py"]
```

**Build and run:**
```bash
# Build image
docker build -t stale-branch-notifier .

# Run container
docker run --rm \
  -v $(pwd)/config.yaml:/app/config.yaml \
  stale-branch-notifier
```

**Docker Compose with scheduling:**
```yaml
version: '3.8'
services:
  notifier:
    build: .
    volumes:
      - ./config.yaml:/app/config.yaml
    environment:
      - GITLAB_TOKEN=${GITLAB_TOKEN}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
```

Use with external scheduler like `cron` or Kubernetes CronJob.

## Common Scenarios

### Scenario 1: First Time Setup

**Goal:** Test the setup without sending emails

```bash
# 1. Create and edit configuration
cp config.yaml.example config.yaml
nano config.yaml

# 2. Test with dry run
python stale_branch_notifier.py --dry-run -v

# 3. Review output, verify:
#    - GitLab connection works
#    - Projects are found
#    - Stale items are detected correctly
#    - Email routing looks correct

# 4. Send test email to yourself
# (Temporarily set fallback_email to your email)
python stale_branch_notifier.py --dry-run

# 5. Verify email looks good, then go live
python stale_branch_notifier.py
```

### Scenario 2: Weekly Team Cleanup

**Goal:** Remind team weekly about stale branches

```bash
# 1. Configure for your team
vim config.yaml
# Set stale_days: 21 (3 weeks)
# Set cleanup_weeks: 4
# Set fallback_email: "team-leads@company.com"

# 2. Add to cron (every Monday 9 AM)
crontab -e
# Add: 0 9 * * 1 cd /path/to/repo && /path/to/python stale_branch_notifier.py

# 3. Monitor first few runs
tail -f /var/log/cron.log
```

### Scenario 3: Pre-Release Cleanup

**Goal:** Clean up before major release

```bash
# 1. Use stricter settings temporarily
python stale_branch_notifier.py -c config.pre-release.yaml
```

**config.pre-release.yaml:**
```yaml
# ... same as config.yaml but with:
stale_days: 14  # More aggressive
cleanup_weeks: 2  # Shorter timeline
```

### Scenario 4: Multiple GitLab Instances

**Goal:** Monitor projects across different GitLab servers

```bash
# Create separate configs for each instance
# gitlab-company.yaml
gitlab:
  url: "https://gitlab.company.com"
  private_token: "token-1"
# ...

# gitlab-opensource.yaml
gitlab:
  url: "https://gitlab.com"
  private_token: "token-2"
# ...

# Run separately
python stale_branch_notifier.py -c gitlab-company.yaml
python stale_branch_notifier.py -c gitlab-opensource.yaml
```

### Scenario 5: Audit Mode

**Goal:** Generate report without sending emails

```bash
# Run with dry-run and redirect output
python stale_branch_notifier.py --dry-run -v > stale-branches-report.txt 2>&1

# Review report
less stale-branches-report.txt

# Extract just the summary
tail -20 stale-branches-report.txt

# Share with team
cat stale-branches-report.txt | mail -s "Stale Branch Report" team@company.com
```

## Advanced Usage

### Custom Email Templates

**1. Save current template:**
```bash
# Extract template from script
grep -A 100 "EMAIL_TEMPLATE = " stale_branch_notifier.py > email-template.html
```

**2. Modify template:**
Edit `email-template.html` with your changes

**3. Update script:**
Replace `EMAIL_TEMPLATE` in `stale_branch_notifier.py`

### Filtering Specific Projects

**Temporarily monitor only certain projects:**

```bash
# Create temporary config
cat > config.temp.yaml << EOF
gitlab:
  url: "https://gitlab.company.com"
  private_token: "your-token"

projects:
  - 123  # Only this project

stale_days: 30
cleanup_weeks: 4
fallback_email: "you@company.com"

smtp:
  # ... your SMTP settings
EOF

# Run with temp config
python stale_branch_notifier.py -c config.temp.yaml --dry-run
```

### Notification to Specific Person

**Override all routing to send to one person (for testing):**

Temporarily modify `config.yaml`:
```yaml
fallback_email: "your-test-email@company.com"
```

Then manually mark all users as inactive in your test, or modify the routing logic temporarily.

### Batch Processing Large Repos

**For repositories with 100+ stale branches:**

```bash
# Use verbose mode to track progress
python stale_branch_notifier.py -v 2>&1 | tee processing.log

# Monitor in real-time
tail -f processing.log
```

## Tips and Tricks

### Tip 1: Start with Lenient Settings

When first deploying:
```yaml
stale_days: 60  # Start lenient
cleanup_weeks: 8  # Give plenty of time
```

Gradually decrease over time as team adapts.

### Tip 2: Schedule During Low-Traffic Hours

```bash
# Off-hours scheduling (3 AM)
0 3 * * 1 cd /path/to/repo && /path/to/python stale_branch_notifier.py

# OR during team standup (developers are already thinking about work)
0 9 * * 1 cd /path/to/repo && /path/to/python stale_branch_notifier.py
```

### Tip 3: Combine with Branch Protection

After notification, protect main branches:

```bash
# After cleaning up, ensure main is protected
# (Use GitLab UI or API to protect branches)
```

### Tip 4: Monitor Email Delivery

**Create a monitoring script:**

```python
#!/usr/bin/env python3
import subprocess
import sys

result = subprocess.run(
    ['python', 'stale_branch_notifier.py'],
    capture_output=True,
    text=True
)

# Check for failures
if 'emails_failed: 0' not in result.stdout:
    print("⚠️ Some emails failed to send!")
    sys.exit(1)
else:
    print("✅ All emails sent successfully")
```

### Tip 5: Create Summary Dashboard

**Extract data for dashboard:**

```bash
# Get counts
python stale_branch_notifier.py --dry-run -v 2>&1 | grep "Total stale"

# Parse into metrics
python stale_branch_notifier.py --dry-run -v 2>&1 | \
  grep "Total stale" | \
  awk '{print $5}' | \
  paste -sd+ | bc
```

### Tip 6: Notification Digest Mode

**Send one summary email to team leads:**

Modify `fallback_email` to team list and temporarily set all users as "inactive" in logic to consolidate notifications.

### Tip 7: Integration with Slack/Teams

**Webhook integration:**

```python
# Add to script
import requests

def send_slack_notification(summary):
    webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    message = {
        "text": f"🧹 Stale Branch Cleanup: {summary['total_stale_branches']} branches, "
                f"{summary['total_stale_merge_requests']} MRs found. "
                f"Notifications sent to {summary['emails_sent']} developers."
    }
    requests.post(webhook_url, json=message)

# Call after sending emails
send_slack_notification(summary)
```

## See Also

- [Setup Guide](SETUP_GUIDE.md) - Initial setup instructions
- [Configuration Reference](CONFIGURATION.md) - All config options
- [Email Notifications](EMAIL_NOTIFICATIONS.md) - Email details
- [FAQ](FAQ.md) - Common questions
