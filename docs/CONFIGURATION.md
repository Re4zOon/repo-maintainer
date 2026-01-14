# Configuration Reference

Complete reference for all configuration options in `config.yaml`.

## Configuration File Structure

The configuration file uses YAML format and is divided into several sections:

```yaml
gitlab:
  # GitLab connection settings

projects:
  # List of project IDs to monitor

stale_days: # Staleness threshold
cleanup_weeks: # Cleanup timeline
fallback_email: # Default notification email

smtp:
  # Email server settings
```

## GitLab Section

Controls connection to your GitLab instance.

### `gitlab.url`

- **Type**: String
- **Required**: Yes
- **Description**: The URL of your GitLab instance
- **Examples**:
  - `"https://gitlab.com"` - GitLab.com (SaaS)
  - `"https://gitlab.company.com"` - Self-hosted
  - `"https://git.example.org"` - Custom domain

**Note**: Must include the protocol (`https://` or `http://`)

### `gitlab.private_token`

- **Type**: String
- **Required**: Yes
- **Description**: GitLab personal access token for API authentication
- **Scopes Required**: `read_api`
- **Format**: Usually starts with `glpat-` for newer tokens
- **Security**: Keep this secret! Never commit to version control

**How to generate**:
1. GitLab → User Settings → Access Tokens
2. Create token with `read_api` scope
3. Copy token immediately (shown only once)

**Example**:
```yaml
gitlab:
  private_token: "glpat-xxxxxxxxxxxxxxxxxxxx"
```

## Projects Section

List of GitLab project IDs to monitor for stale branches.

### `projects`

- **Type**: List of integers
- **Required**: Yes (at least one project)
- **Description**: GitLab project IDs to scan for stale branches
- **How to find**: GitLab Project → Settings → General → Project ID

**Examples**:

Single project:
```yaml
projects:
  - 123
```

Multiple projects:
```yaml
projects:
  - 123
  - 456
  - 789
  - 1011
```

**Note**: The script will process all projects in the list and aggregate stale items by developer.

## Staleness Criteria

### `stale_days`

- **Type**: Integer
- **Required**: No
- **Default**: `30`
- **Description**: Number of days of inactivity before an item is considered stale
- **Range**: Recommended 7-90 days

**How it works**:
- For **branches**: Checks last commit date
- For **merge requests**: Checks last update date (any activity)

**Examples**:

```yaml
# Aggressive cleanup (2 weeks)
stale_days: 14

# Default (1 month)
stale_days: 30

# Lenient (2 months)
stale_days: 60
```

**Choosing the right value**:
- **14-21 days**: Fast-moving teams, short-lived branches
- **30 days**: General development (default)
- **45-60 days**: Long-term features, research projects
- **90+ days**: Archive projects, slow-moving initiatives

### `cleanup_weeks`

- **Type**: Integer
- **Required**: No
- **Default**: `4`
- **Description**: Number of weeks mentioned in notification before automatic cleanup
- **Note**: This is informational only; the tool doesn't perform automatic cleanup

**Examples**:

```yaml
# Quick turnaround
cleanup_weeks: 2

# Standard timeline
cleanup_weeks: 4

# Extended grace period
cleanup_weeks: 8
```

**Purpose**: Sets expectations in the notification email about when items will be cleaned up (assuming you have a separate cleanup process).

## Email Routing

### `fallback_email`

- **Type**: String
- **Required**: Highly recommended
- **Default**: None (items will be skipped if no email found)
- **Description**: Email address to use when primary recipient cannot be determined

**When fallback is used**:
1. User account is inactive/deactivated in GitLab
2. MR has no assignee or author
3. Branch committer email not found in GitLab
4. Email address cannot be determined

**Examples**:

Team mailing list:
```yaml
fallback_email: "dev-team@company.com"
```

Maintainers group:
```yaml
fallback_email: "repo-maintainers@company.com"
```

Individual backup:
```yaml
fallback_email: "tech-lead@company.com"
```

**Best Practice**: Use a team email or group that monitors regularly.

## SMTP Section

Email server configuration for sending notifications.

### `smtp.host`

- **Type**: String
- **Required**: Yes
- **Description**: SMTP server hostname
- **Examples**:
  - `"smtp.gmail.com"` - Gmail
  - `"smtp.office365.com"` - Office 365
  - `"smtp.company.com"` - Corporate server

### `smtp.port`

- **Type**: Integer
- **Required**: Yes
- **Common Values**:
  - `587` - STARTTLS (most common, recommended)
  - `465` - SSL/TLS
  - `25` - Plain SMTP (not recommended)

**Example**:
```yaml
smtp:
  port: 587
```

### `smtp.use_tls`

- **Type**: Boolean
- **Required**: No
- **Default**: `true`
- **Description**: Whether to use TLS encryption
- **Values**: `true` or `false`

**Examples**:

```yaml
# Use TLS (recommended)
smtp:
  use_tls: true

# No TLS (only for testing or internal networks)
smtp:
  use_tls: false
```

**Security Note**: Always use TLS in production environments.

### `smtp.username`

- **Type**: String
- **Required**: Depends on server
- **Description**: SMTP authentication username
- **Format**: Usually an email address

**Examples**:
```yaml
smtp:
  username: "notifications@company.com"
  # or
  username: "smtp-user-123"
```

### `smtp.password`

- **Type**: String
- **Required**: Depends on server
- **Description**: SMTP authentication password
- **Security**: Keep secret! Consider using environment variables

**For Gmail**: Use [App Password](https://support.google.com/accounts/answer/185833), not your regular password

**Example**:
```yaml
smtp:
  password: "your-smtp-password"
```

**Security Best Practice**: Use environment variables:
```python
import os
config['smtp']['password'] = os.environ.get('SMTP_PASSWORD')
```

### `smtp.from_email`

- **Type**: String
- **Required**: Yes
- **Description**: Sender email address and display name
- **Format**: `"Display Name <email@address.com>"` or `"email@address.com"`

**Examples**:

With display name:
```yaml
smtp:
  from_email: "GitLab Maintenance <noreply@company.com>"
```

Simple email:
```yaml
smtp:
  from_email: "noreply@company.com"
```

Branded:
```yaml
smtp:
  from_email: "🤖 Repo Bot <bot@company.com>"
```

## Complete Configuration Examples

### Example 1: Startup/Small Team

```yaml
gitlab:
  url: "https://gitlab.com"
  private_token: "glpat-abcdefghijklmnop"

projects:
  - 12345
  - 67890

stale_days: 21
cleanup_weeks: 3

fallback_email: "tech@startup.com"

smtp:
  host: "smtp.gmail.com"
  port: 587
  use_tls: true
  username: "notifications@startup.com"
  password: "app-password-here"
  from_email: "GitLab Bot <notifications@startup.com>"
```

### Example 2: Enterprise/Large Organization

```yaml
gitlab:
  url: "https://gitlab.enterprise.com"
  private_token: "glpat-xxxxxxxxxxxxxxxxxxx"

projects:
  - 101
  - 102
  - 103
  - 104
  - 105
  - 106

stale_days: 30
cleanup_weeks: 6

fallback_email: "repo-maintainers@enterprise.com"

smtp:
  host: "smtp.enterprise.com"
  port: 587
  use_tls: true
  username: "gitlab-bot@enterprise.com"
  password: "secure-password"
  from_email: "GitLab Maintenance Team <gitlab-bot@enterprise.com>"
```

### Example 3: Open Source Project

```yaml
gitlab:
  url: "https://gitlab.com"
  private_token: "glpat-opensource-token"

projects:
  - 999888

stale_days: 45
cleanup_weeks: 8

fallback_email: "maintainers@opensource-project.org"

smtp:
  host: "smtp.sendgrid.net"
  port: 587
  use_tls: true
  username: "apikey"
  password: "sendgrid-api-key"
  from_email: "Project Bot <bot@opensource-project.org>"
```

## Environment Variables

For better security, sensitive values can be loaded from environment variables:

### Using Environment Variables in Python

Modify the script to load from environment:

```python
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# In config loading section
config['gitlab']['private_token'] = os.getenv('GITLAB_TOKEN')
config['smtp']['password'] = os.getenv('SMTP_PASSWORD')
```

### `.env` file example:

```bash
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
SMTP_PASSWORD=your-smtp-password
```

**Security**: Add `.env` to `.gitignore`!

## Configuration Validation

The script validates configuration on startup. Common errors:

### Missing Required Fields

```
ConfigurationError: Missing 'gitlab' section in configuration
```

**Fix**: Add all required sections

### Invalid Project IDs

```
GitlabGetError: 404 Project Not Found
```

**Fix**: Verify project IDs in GitLab UI

### SMTP Authentication Failed

```
SMTPAuthenticationError: (535, b'5.7.8 Username and Password not accepted')
```

**Fix**: Check username/password, use app passwords for Gmail

## Advanced Configuration Patterns

### Multiple Configuration Files

Use different configs for different environments:

```bash
# Development
python stale_branch_notifier.py -c config.dev.yaml

# Production
python stale_branch_notifier.py -c config.prod.yaml
```

### Partial Configurations

You can maintain a base config and override specific values:

**config.base.yaml**:
```yaml
stale_days: 30
cleanup_weeks: 4
```

**config.prod.yaml**:
```yaml
gitlab:
  url: "https://gitlab.company.com"
  private_token: "production-token"
# ... rest of config
```

### Dynamic Project Lists

Generate project list programmatically:

```python
# Get all projects from a GitLab group
gl = gitlab.Gitlab(url, token)
group = gl.groups.get(group_id)
projects = [p.id for p in group.projects.list(all=True)]

config['projects'] = projects
```

## Troubleshooting Configuration

### Test Configuration

```bash
# Dry run to test without sending emails
python stale_branch_notifier.py --dry-run -v
```

### Validate YAML Syntax

```bash
# Using Python
python -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Using yamllint (if installed)
yamllint config.yaml
```

### Common YAML Mistakes

❌ **Wrong**:
```yaml
projects: 123  # Not a list!
```

✅ **Correct**:
```yaml
projects:
  - 123
```

❌ **Wrong**:
```yaml
stale_days: "30"  # String instead of number
```

✅ **Correct**:
```yaml
stale_days: 30
```

## See Also

- [Setup Guide](SETUP_GUIDE.md) - Step-by-step setup instructions
- [Email Notifications](EMAIL_NOTIFICATIONS.md) - Understanding email routing
- [Usage Examples](USAGE_EXAMPLES.md) - Common usage patterns
- [FAQ](FAQ.md) - Frequently asked questions
