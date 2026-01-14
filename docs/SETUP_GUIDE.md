# Setup Guide

This guide will walk you through the complete setup process for the GitLab Stale Branch/Merge Request Notifier.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [GitLab Configuration](#gitlab-configuration)
- [SMTP Configuration](#smtp-configuration)
- [Testing Your Setup](#testing-your-setup)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before you begin, ensure you have the following:

- **Python 3.7 or higher** installed on your system
- **GitLab access** with permissions to read projects and branches
- **SMTP server access** for sending email notifications (e.g., Gmail, Office 365, or your company's SMTP server)

You can check your Python version:
```bash
python --version
# or
python3 --version
```

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Re4zOon/repo-maintainer.git
cd repo-maintainer
```

### 2. Install Dependencies

Using pip:
```bash
pip install -r requirements.txt
```

Or using a virtual environment (recommended):
```bash
# Create virtual environment
python -m venv venv

# Activate it
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Verify Installation

Check that the dependencies were installed correctly:
```bash
python -c "import gitlab, yaml, jinja2; print('All dependencies installed successfully!')"
```

## GitLab Configuration

### Step 1: Create a GitLab Access Token

1. Log in to your GitLab instance
2. Click on your **profile picture** (top-right corner)
3. Select **Preferences** → **Access Tokens**
4. Create a new token with:
   - **Name**: `repo-maintainer-bot` (or any descriptive name)
   - **Scopes**: Select `read_api` (read-only access to API)
   - **Expiration date**: Set according to your security policies
5. Click **Create personal access token**
6. **Important**: Copy the token immediately! You won't be able to see it again.

### Step 2: Find Your Project IDs

You need the project IDs for repositories you want to monitor:

1. Navigate to your GitLab project
2. Go to **Settings** → **General**
3. Look for **Project ID** at the top of the page
4. Note down the ID (it's a number like `123`)

Repeat this for all projects you want to monitor.

### Step 3: Configure the Tool

Copy the example configuration file:
```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` with your favorite text editor:
```yaml
# GitLab connection settings
gitlab:
  url: "https://gitlab.example.com"  # Your GitLab instance URL
  private_token: "glpat-xxxxxxxxxxxx"  # Your access token from Step 1

# Project IDs to monitor (from Step 2)
projects:
  - 123
  - 456
  - 789

# Number of days before a branch is considered stale
stale_days: 30

# Weeks until automatic cleanup (shown in notification)
cleanup_weeks: 4

# Fallback email for notifications
fallback_email: "repo-maintainers@example.com"

# SMTP settings (see next section)
smtp:
  host: "smtp.example.com"
  port: 587
  use_tls: true
  username: "notifications@example.com"
  password: "your-smtp-password"
  from_email: "GitLab Maintenance <notifications@example.com>"
```

## SMTP Configuration

The tool needs SMTP access to send email notifications. Here are configurations for common providers:

### Gmail

```yaml
smtp:
  host: "smtp.gmail.com"
  port: 587
  use_tls: true
  username: "your-email@gmail.com"
  password: "your-app-password"  # See note below
  from_email: "GitLab Bot <your-email@gmail.com>"
```

**Note for Gmail**: You need to create an [App Password](https://support.google.com/accounts/answer/185833):
1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account → Security → App passwords
3. Generate a new app password
4. Use this password in the configuration

### Office 365

```yaml
smtp:
  host: "smtp.office365.com"
  port: 587
  use_tls: true
  username: "notifications@yourdomain.com"
  password: "your-password"
  from_email: "GitLab Notifications <notifications@yourdomain.com>"
```

### Custom SMTP Server

```yaml
smtp:
  host: "smtp.yourcompany.com"
  port: 587  # Common ports: 587 (TLS), 465 (SSL), 25 (Plain)
  use_tls: true  # Set to false if not using TLS
  username: "smtp-username"
  password: "smtp-password"
  from_email: "GitLab Maintenance <noreply@yourcompany.com>"
```

### Testing SMTP Connection

You can test your SMTP settings with Python:

```python
import smtplib

smtp_config = {
    'host': 'smtp.gmail.com',
    'port': 587,
    'username': 'your-email@gmail.com',
    'password': 'your-app-password'
}

try:
    with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
        server.starttls()
        server.login(smtp_config['username'], smtp_config['password'])
        print("✅ SMTP connection successful!")
except Exception as e:
    print(f"❌ SMTP connection failed: {e}")
```

## Testing Your Setup

### 1. Run a Dry-Run Test

Test the configuration without sending actual emails:

```bash
python stale_branch_notifier.py --dry-run -v
```

This will:
- Connect to GitLab
- Find stale branches and merge requests
- Show what emails would be sent
- **Not actually send any emails**

Expected output:
```
INFO - Connecting to GitLab...
INFO - Checking project: my-awesome-project (ID: 123)
INFO - Found 3 stale branches
INFO - Found 1 stale merge request
INFO - [DRY RUN] Would send email to: developer@example.com
INFO - ==========================================
INFO - Stale Branch/MR Notification Summary
INFO - ==========================================
INFO - Total stale branches found: 3
INFO - Total stale merge requests found: 1
INFO - Emails sent: 1
```

### 2. Test with Actual Email

Once dry-run looks good, test with real email:

```bash
python stale_branch_notifier.py -v
```

Check the recipient's inbox for the notification email.

### 3. Schedule Regular Runs

Set up a cron job (Linux/Mac) or Task Scheduler (Windows) to run the script regularly:

**Cron example** (runs every Monday at 9 AM):
```bash
0 9 * * 1 cd /path/to/repo-maintainer && /path/to/venv/bin/python stale_branch_notifier.py
```

**GitLab CI/CD example**:
```yaml
# .gitlab-ci.yml
stale-branch-check:
  image: python:3.9
  before_script:
    - pip install -r requirements.txt
  script:
    - python stale_branch_notifier.py
  only:
    - schedules
```

Then create a scheduled pipeline in GitLab (CI/CD → Schedules).

## Troubleshooting

### Issue: "Configuration file not found"

**Solution**: Make sure you've created `config.yaml` in the project directory:
```bash
cp config.yaml.example config.yaml
# Then edit config.yaml with your settings
```

### Issue: "GitLab authentication failed"

**Possible causes**:
1. Invalid or expired access token
2. Incorrect GitLab URL
3. Network/firewall issues

**Solution**:
- Verify your access token in GitLab settings
- Check that the GitLab URL is correct (including `https://`)
- Test connectivity: `curl https://your-gitlab-instance.com`

### Issue: "Failed to send email"

**Possible causes**:
1. Incorrect SMTP credentials
2. Firewall blocking SMTP port
3. Wrong SMTP host/port

**Solution**:
- Verify SMTP settings with the test script above
- Check if port 587 (or your configured port) is open
- Try without TLS: set `use_tls: false` (not recommended for production)

### Issue: "No stale branches found"

This might not be an issue! It means:
- All branches are active (recent commits)
- All branches are protected (main/master)
- No projects configured

**Verify**:
```bash
python stale_branch_notifier.py --dry-run -v
```

Look for messages about protected branches being skipped.

### Issue: "Permission denied" errors

**Solution**:
- Ensure your GitLab token has `read_api` scope
- Verify you have access to the configured projects
- Check that project IDs are correct

### Getting Help

If you encounter issues not covered here:

1. Run with verbose logging: `python stale_branch_notifier.py -v`
2. Check the error messages carefully
3. Review the [FAQ document](FAQ.md)
4. Open an issue on GitHub with:
   - Error message (sanitize sensitive data!)
   - Python version
   - OS information
   - Steps to reproduce

## Next Steps

- Read the [Email Notifications Guide](EMAIL_NOTIFICATIONS.md) to understand how notifications work
- Check out the [Configuration Reference](CONFIGURATION.md) for advanced options
- See [Usage Examples](USAGE_EXAMPLES.md) for common scenarios
