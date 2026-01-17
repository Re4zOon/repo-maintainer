# GitLab Stale Branch/Merge Request Notifier and Auto-Archiver

A Python script that identifies stale branches and merge requests in GitLab projects, sends email notifications to their owners about upcoming cleanup, and can automatically archive very old stale items.

## Features

- **Detect stale merge requests** based on any activity (commits, comments, reviews, etc.)
- **Detect stale branches** where the last commit is older than a configurable number of days (if no MR exists)
- **Smart MR activity detection** - checks both MR metadata updates and note/comment activity
- **Smart email routing for MRs** - uses MR assignee, author, or fallback email for notifications
- **Check committer status** - verifies if the committer's GitLab profile is active
- **Smart email routing for branches** - uses fallback email if the committer's profile is inactive
- **HTML email notifications** including:
  - List of stale merge requests with project, MR link, and last activity information
  - List of stale branches with project and commit information
  - Notification for cleanup action required
  - Warning about automatic cleanup after a configurable number of weeks
- **MR reminder comments** - posts friendly, humorous reminder comments directly on stale MRs for increased visibility
- **Automatic archiving** of very old stale branches and MRs that have exceeded the cleanup period:
  - Exports the branch to a compressed local archive (tar.gz)
  - Closes associated merge requests with an explanatory note
  - Deletes the source branch
  - Safety-first approach: branch is only deleted after successful export
- **Dry-run mode** for testing without sending emails or performing archiving
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
# IMPORTANT: Only the repositories listed here will be scanned.
# This script does NOT scan all repositories in your GitLab instance.
# You must explicitly list each project ID you want to monitor.
projects:
  - 123
  - 456

# Number of days after which a branch is considered stale
stale_days: 30

# Number of weeks until automatic cleanup/archiving
# After stale_days + (cleanup_weeks * 7) days, items become eligible for archiving
cleanup_weeks: 4

# Fallback email for inactive users or when MR assignee/author cannot be identified
fallback_email: "repo-maintainers@example.com"

# SMTP settings
smtp:
  host: "smtp.example.com"
  port: 587
  use_tls: true
  username: "notifications@example.com"
  password: "your-smtp-password"
  from_email: "GitLab Maintenance <notifications@example.com>"

# Automatic archiving settings (optional)
enable_auto_archive: false  # Enable via config, or use --archive flag
archive_folder: "./archived_branches"  # Where to store branch archives

# MR reminder comments settings (optional)
enable_mr_comments: false        # Enable posting reminder comments on stale MRs
mr_comment_inactivity_days: 14   # Days of inactivity before first comment
mr_comment_frequency_days: 7     # Days between subsequent comments
```

## Usage

### Basic Usage

```bash
python stale_branch_mr_handler.py
```

### With Custom Configuration File

```bash
python stale_branch_mr_handler.py -c /path/to/config.yaml
```

### Dry Run (No Emails Sent or Archiving Performed)

```bash
python stale_branch_mr_handler.py --dry-run
```

### Verbose Output

```bash
python stale_branch_mr_handler.py -v
```

### Automatic Archiving

Enable automatic archiving to clean up very old stale branches and MRs. Items are archived when they have been stale for `stale_days + (cleanup_weeks * 7)` days (default: 58 days).

```bash
# Enable via command line flag (one-time)
python stale_branch_mr_handler.py --archive

# Or enable in config.yaml for automatic runs
# enable_auto_archive: true

# Dry run to see what would be archived
python stale_branch_mr_handler.py --archive --dry-run
```

The archiving process:
1. **Exports** the branch to a compressed archive (tar.gz) in the `archive_folder`
2. **Closes** any associated merge requests with an explanatory note
3. **Deletes** the source branch (only after successful export for safety)

### MR Reminder Comments

Enable MR reminder comments to post friendly, humorous reminders directly on stale merge requests. This provides additional visibility without affecting email notifications or archiving.

```yaml
# Enable in config.yaml
enable_mr_comments: true
mr_comment_inactivity_days: 14  # Post first comment after 14 days of inactivity
mr_comment_frequency_days: 7    # Post new comments every 7 days
```

When enabled, the bot will:
1. Identify MRs with no activity for X days (`mr_comment_inactivity_days`)
2. Post a friendly reminder comment directly on the MR
3. Continue posting new comments every Y days (`mr_comment_frequency_days`) if the MR remains inactive

The comments are designed to be clear and encourage action while keeping things light with a touch of humor. Example:

> 🧹 The cleanup bot is back! This MR hasn't had any activity recently. Don't worry, I'm not here to judge, just to remind. Maybe merge it? Maybe close it? The suspense is killing me! 😅

## WebUI for Monitoring and Configuration

The tool includes a web-based interface for monitoring statistics and managing configuration. The WebUI provides:

- **Dashboard** with real-time statistics on notifications and MR comments
- **Configuration management** to update settings without editing files
- **Dark mode** support for comfortable viewing
- **Responsive design** that works on desktop and mobile

### Running the WebUI

#### With Docker Compose (Recommended)

The WebUI runs as a separate service in Docker Compose:

```bash
# Start both the CLI tool and WebUI
docker compose up --build

# Or start just the WebUI
docker compose up repo-maintainer-webui --build
```

Access the WebUI at: `http://localhost:5000`

Default credentials:
- Username: `admin`
- Password: `admin`

**Important:** Change the default credentials in production by setting environment variables:

```yaml
# In docker-compose.yml
environment:
  - WEBUI_USERNAME=your-secure-username
  - WEBUI_PASSWORD=your-secure-password
  - WEBUI_SECRET_KEY=your-secret-key
```

#### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the WebUI
python -m webui.app -c config.yaml

# With custom port
python -m webui.app -c config.yaml --port 8080

# In debug mode
python -m webui.app -c config.yaml --debug
```

### WebUI Features

#### Dashboard
- Total notifications sent (branches and MRs)
- MR comments posted
- Current configuration summary
- Recent notification history
- Export statistics as JSON

#### Configuration
- Update stale detection settings
- Configure notification frequency
- Enable/disable auto-archive and MR comments
- Manage monitored projects

Note: Sensitive settings (API tokens, passwords) cannot be modified through the WebUI for security reasons.

### WebUI API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | No | Health check |
| `/api/stats` | GET | Yes | Get statistics |
| `/api/config` | GET | Yes | Get configuration (sanitized) |
| `/api/config` | PUT | Yes | Update configuration |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBUI_HOST` | `0.0.0.0` | Host to bind the server |
| `WEBUI_PORT` | `5000` | Port for the WebUI |
| `WEBUI_USERNAME` | `admin` | Username for authentication |
| `WEBUI_PASSWORD` | `admin` | Password for authentication |
| `WEBUI_SECRET_KEY` | - | Secret key for sessions |
| `CONFIG_PATH` | `config.yaml` | Path to config file |

## Docker Deployment

### Quick Start with Docker Compose

1. Copy the example configuration:
   ```bash
   cp config.yaml.example config.yaml
   # Edit config.yaml with your settings
   ```

2. Create a data directory for the notification database:
   ```bash
   mkdir -p data
   ```

3. Run the container:
   ```bash
   docker compose up --build
   ```

### Run with Dry Run Mode

```bash
docker compose run --rm repo-maintainer python stale_branch_mr_handler.py -c /app/config.yaml --dry-run
```

### Run with Verbose Output

```bash
docker compose run --rm repo-maintainer python stale_branch_mr_handler.py -c /app/config.yaml -v
```

### Scheduled Execution with Cron

To run the notifier on a schedule (e.g., daily), add a cron job on your host:

```bash
# Run daily at 9:00 AM (omit --build if the image is already built)
0 9 * * * cd /path/to/repo-maintainer && docker compose up
```

### Build and Run Manually with Docker

```bash
# Build the image
docker build -t repo-maintainer .

# Run the container (run from the project directory)
docker run --rm \
  -v ./config.yaml:/app/config.yaml:ro \
  -v ./data:/app/data \
  repo-maintainer
```

## How It Works

### Notification Mode (default)

1. **Connects to GitLab** using the provided API token
2. **Iterates through configured projects** and retrieves all open merge requests
3. **Identifies stale MRs** based on the latest activity (including notes/comments)
4. **Filters out protected branches** (main, master, etc.)
5. **Identifies stale branches** based on the last commit date (only for branches without open MRs)
6. **For stale MRs**: Groups by MR assignee/author email and sends MR notifications
7. **For stale branches without MRs**: Groups by branch committer email
8. **Checks if users are active** in GitLab
9. **Sends notification emails** to active users, or to fallback email for inactive users

### Automatic Archiving Mode (with `--archive` flag or `enable_auto_archive: true`)

After sending notifications, if archiving is enabled:

1. **Identifies items ready for archiving** - items that have been stale for at least `stale_days + (cleanup_weeks * 7)` days
2. **For each item**:
   - **Exports** the branch to a compressed tar.gz archive in the `archive_folder`
   - **If MR exists**: Adds a note explaining the automatic closure and closes the MR
   - **Deletes** the source branch (only after successful export)
3. **Logs results** showing which items were archived successfully and any failures

**Safety measures**:
- Branches are only deleted after the archive is successfully created
- Protected branches are never archived or deleted
- All operations are logged for audit purposes
- Use `--dry-run` to preview what would be archived without making changes

## Email Template

The notification email includes:
- List of stale merge requests with project name, MR link, source branch, and last update date
- List of stale branches with project name, branch name, and last commit date
- Instructions for handling the items (merge, update, close, or delete)
- Warning about automatic cleanup timeline

The template also includes a friendly reminder from the cleanup bot to keep the tone light.

### Email Notification Preview

Example subject lines:
- `[Action Required] 3 Stale Item(s) Require Attention`
- `[Action Required] 1 Stale Merge Request(s) Require Attention`
- `[Action Required] 2 Stale Branch(es) Require Attention`

Example email excerpt (MRs + branches):

```
Hello,
This is your friendly nudge from the cleanup bot 🤖. The following items have been snoozing
for 30 days and could use a check-in:

Stale Merge Requests:
- Payments API: !42 - Add retry logic (source branch: retry-payments, last updated 2024-02-12 by Priya)

Stale Branches:
- Mobile App: feature/dark-mode (last commit 2023-12-18 by Sam)

⚠️ Important: Items that remain inactive will be automatically cleaned up after 4 weeks.
```

![Example notification email](docs/images/email-notification.png)

To customize the notification layout or wording, edit `EMAIL_TEMPLATE` in
`stale_branch_mr_handler.py`.

## Running Tests

```bash
python -m unittest discover tests/ -v
```

## Finding Project IDs

To find the project ID for a GitLab repository:

1. **Via GitLab UI**: Navigate to your project's main page. The Project ID is displayed in the "Project overview" section or under "Settings > General".

2. **Via GitLab API**:
   ```bash
   curl --header "PRIVATE-TOKEN: your-token" "https://gitlab.example.com/api/v4/projects?search=project-name"
   ```
   The response will include the `id` field for each matching project.

## Requirements

- Python 3.7+
- GitLab API access (private token with `read_api` scope)
- SMTP server for sending emails

## License

MIT License
