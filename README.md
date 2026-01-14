# GitLab Stale Branch Notifier

A Python script that identifies stale branches in GitLab projects and sends email notifications to their committers about upcoming cleanup.

## Features

- **Collect branches** from a list of GitLab projects
- **Identify stale branches** where the last commit is older than a configurable number of days
- **Check committer status** - verifies if the committer's GitLab profile is active
- **Smart email routing** - uses fallback email if the committer's profile is inactive
- **HTML email notifications** including:
  - List of stale branches with project and commit information
  - Notification for cleanup action required
  - Warning about automatic cleanup after a configurable number of weeks
- **Dry-run mode** for testing without sending emails
- **Skips protected branches** to avoid notifying about main/master branches

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Re4zOon/repo-maintainer.git
   cd repo-maintainer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example configuration and edit it:
   ```bash
   cp config.yaml.example config.yaml
   # Edit config.yaml with your settings
   ```

## Configuration

Create a `config.yaml` file with the following settings:

```yaml
# GitLab connection settings
gitlab:
  url: "https://gitlab.example.com"
  private_token: "your-gitlab-private-token"

# Project IDs to check for stale branches
projects:
  - 123
  - 456

# Number of days after which a branch is considered stale
stale_days: 30

# Number of weeks until automatic cleanup (mentioned in notification)
cleanup_weeks: 4

# Fallback email for inactive users
fallback_email: "repo-maintainers@example.com"

# SMTP settings
smtp:
  host: "smtp.example.com"
  port: 587
  use_tls: true
  username: "notifications@example.com"
  password: "your-smtp-password"
  from_email: "GitLab Maintenance <notifications@example.com>"
```

## Usage

### Basic Usage

```bash
python stale_branch_notifier.py
```

### With Custom Configuration File

```bash
python stale_branch_notifier.py -c /path/to/config.yaml
```

### Dry Run (No Emails Sent)

```bash
python stale_branch_notifier.py --dry-run
```

### Verbose Output

```bash
python stale_branch_notifier.py -v
```

## How It Works

1. **Connects to GitLab** using the provided API token
2. **Iterates through configured projects** and retrieves all branches
3. **Filters out protected branches** (main, master, etc.)
4. **Identifies stale branches** based on the last commit date
5. **Groups branches by committer email**
6. **Checks if committers are active** in GitLab
7. **Sends notification emails** to active users, or to fallback email for inactive users

## Email Template

The notification email includes:
- List of stale branches with project name, branch name, and last commit date
- Instructions for handling the branches (merge, update, or delete)
- Warning about automatic cleanup timeline

## Running Tests

```bash
python -m unittest discover tests/ -v
```

## Requirements

- Python 3.7+
- GitLab API access (private token with `read_api` scope)
- SMTP server for sending emails

## License

MIT License
