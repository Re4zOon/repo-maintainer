# GitLab Stale Branch/Merge Request Notifier

<div align="center">

🧹 **Keep your GitLab repositories clean and organized!** ✨

A friendly Python tool that identifies stale branches and merge requests in GitLab projects and sends beautiful, actionable email notifications to their owners.

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Features](#features) • [Quick Start](#quick-start) • [Documentation](#documentation) • [Examples](#examples)

</div>

---

## ✨ Features

### 🔍 Smart Detection
- **Automatic branch discovery** - Scans all non-protected branches across configured projects
- **Intelligent staleness detection** - Identifies branches and MRs inactive for a configurable period
- **MR-aware** - Detects open merge requests for stale branches and prioritizes MR notifications
- **Protected branch filtering** - Automatically skips main/master and other protected branches

### 📧 Beautiful Email Notifications
- **Friendly, humorous tone** - Makes cleanup notifications less intimidating and more engaging
- **Modern HTML design** - Beautiful, mobile-responsive emails with emojis and clear formatting
- **Grouped notifications** - One email per developer with all their stale items
- **Actionable guidance** - Clear instructions on what to do with stale items

### 🎯 Smart Email Routing
- **Priority-based routing for MRs** - Notifies assignee → author → fallback email
- **Active user verification** - Checks if GitLab accounts are active before sending
- **Fallback handling** - Routes notifications to team leads when users are inactive
- **Configurable recipients** - Flexible email routing based on context

### 🛡️ Safe & Reliable
- **Read-only operations** - Never modifies, deletes, or closes anything in GitLab
- **Dry-run mode** - Test configuration and preview notifications without sending emails
- **Comprehensive logging** - Detailed output for debugging and monitoring
- **Error handling** - Graceful handling of API errors and edge cases

## 🚀 Quick Start

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Re4zOon/repo-maintainer.git
   cd repo-maintainer
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the tool**:
   ```bash
   cp config.yaml.example config.yaml
   nano config.yaml  # Edit with your GitLab and SMTP settings
   ```

4. **Test your setup** (dry run - no emails sent):
   ```bash
   python stale_branch_notifier.py --dry-run -v
   ```

5. **Send your first notifications**:
   ```bash
   python stale_branch_notifier.py
   ```

📚 **Need help?** Check out the [detailed Setup Guide](docs/SETUP_GUIDE.md) for step-by-step instructions.

## ⚙️ Configuration

### Basic Configuration

Create a `config.yaml` file with your settings:

```yaml
# GitLab connection
gitlab:
  url: "https://gitlab.example.com"
  private_token: "your-gitlab-private-token"  # Needs 'read_api' scope

# Projects to monitor (find ID in GitLab: Settings → General → Project ID)
projects:
  - 123
  - 456

# Staleness threshold (days without activity)
stale_days: 30

# Cleanup timeline shown in notification (weeks)
cleanup_weeks: 4

# Fallback email for inactive users or when primary recipient unavailable
fallback_email: "repo-maintainers@example.com"

# Email server settings
smtp:
  host: "smtp.gmail.com"  # or your SMTP server
  port: 587
  use_tls: true
  username: "notifications@example.com"
  password: "your-smtp-password"  # Use app password for Gmail
  from_email: "GitLab Bot <notifications@example.com>"
```

📖 **See the [Configuration Reference](docs/CONFIGURATION.md)** for all available options and detailed explanations.

## 💡 Usage

### Common Commands

```bash
# Standard run - send notifications
python stale_branch_notifier.py

# Test without sending emails (recommended first!)
python stale_branch_notifier.py --dry-run

# Verbose output for debugging
python stale_branch_notifier.py -v

# Dry run with detailed logging
python stale_branch_notifier.py --dry-run -v

# Use custom configuration file
python stale_branch_notifier.py -c /path/to/config.yaml
```

### Automation

**Schedule weekly notifications** (cron example):
```bash
# Every Monday at 9 AM
0 9 * * 1 cd /path/to/repo-maintainer && python stale_branch_notifier.py
```

**GitLab CI/CD** (.gitlab-ci.yml):
```yaml
stale-branch-check:
  image: python:3.9
  before_script:
    - pip install -r requirements.txt
  script:
    - python stale_branch_notifier.py
  only:
    - schedules
```

📚 **More examples**: See [Usage Examples](docs/USAGE_EXAMPLES.md) for automation, Docker, and advanced scenarios.

## 📋 Documentation

### Complete Guides

| Document | Description |
|----------|-------------|
| [⚡ Quick Reference](docs/QUICK_REFERENCE.md) | **Start here!** Command cheat sheet and quick setup |
| [📘 Setup Guide](docs/SETUP_GUIDE.md) | Step-by-step installation and configuration |
| [📧 Email Notifications](docs/EMAIL_NOTIFICATIONS.md) | Email template, routing logic, and examples |
| [📸 Screenshots & Examples](docs/SCREENSHOTS.md) | Visual examples and email preview |
| [⚙️ Configuration Reference](docs/CONFIGURATION.md) | Complete config options and parameters |
| [💻 Usage Examples](docs/USAGE_EXAMPLES.md) | Real-world scenarios and automation |
| [🏗️ Architecture](docs/ARCHITECTURE.md) | Technical architecture and workflow |
| [❓ FAQ](docs/FAQ.md) | Frequently asked questions |

### Quick Links

- [How to get GitLab token](docs/SETUP_GUIDE.md#step-1-create-a-gitlab-access-token)
- [SMTP configuration examples](docs/SETUP_GUIDE.md#smtp-configuration)
- [Email routing explanation](docs/EMAIL_NOTIFICATIONS.md#notification-routing-logic)
- [Customizing emails](docs/EMAIL_NOTIFICATIONS.md#customizing-emails)
- [Automation with cron/CI](docs/USAGE_EXAMPLES.md#automation)
- [Troubleshooting common issues](docs/SETUP_GUIDE.md#troubleshooting)

## 📸 Examples

### Email Notification Preview

Developers receive beautiful, actionable emails like this:

```
┌─────────────────────────────────────────────┐
│  🧹 Time for Some Spring Cleaning! ✨       │
└─────────────────────────────────────────────┘

Hey there, Code Gardener! 👋

🕰️ Whoops! It looks like some of your branches 
have been gathering dust...

🔀 Merge Requests That Need Some Love [2]
  📂 my-project: !42 - Add authentication
  🌿 Branch: feature/auth-system
  🕒 Last updated: 2024-01-01 by Jane Doe

🌳 Lonely Branches [1]
  📂 frontend: experimental/new-ui
  🕒 Last commit: 2023-12-15 by Jane Doe

🎯 What Can You Do?
  ✅ Merge it - Work is done!
  🔄 Update it - Still working on it?
  ❌ Close/Delete it - No longer needed?

⏰ Tick-Tock Alert!
Items that remain inactive will be cleaned up
in 4 weeks. No pressure... actually, yes,
a little pressure. 😅
```

See the full [Email Notifications Guide](docs/EMAIL_NOTIFICATIONS.md) for more details.

## 🔄 How It Works

```
1. Connect to GitLab
   └─► Authenticate with API token
   
2. Scan Projects
   └─► Fetch all branches from configured projects
   
3. Filter Branches
   ├─► Skip protected branches (main, master, etc.)
   └─► Check last commit/update date
   
4. Detect Staleness
   ├─► For branches: Check last commit age
   └─► For MRs: Check last update time
   
5. Route Notifications
   ├─► MR with assignee → Send to assignee
   ├─► MR without assignee → Send to author
   ├─► Branch only → Send to last committer
   └─► User inactive → Send to fallback email
   
6. Send Emails
   ├─► Group all items by recipient
   ├─► Generate beautiful HTML email
   └─► Send via SMTP
```

## 🧪 Running Tests

```bash
# Run all tests
python -m unittest discover tests/ -v

# Run specific test
python -m unittest tests.test_stale_branch_notifier -v
```

## 📋 Requirements

- **Python**: 3.7 or higher
- **GitLab Access**: Private token with `read_api` scope
- **SMTP Server**: For sending email notifications (Gmail, Office 365, etc.)
- **Dependencies**: Listed in `requirements.txt`
  - `python-gitlab >= 3.15.0`
  - `pyyaml >= 6.0`
  - `jinja2 >= 3.1.2`

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. 🐛 **Report bugs** - Open an issue with details
2. 💡 **Suggest features** - Share your ideas
3. 📝 **Improve docs** - Help make guides better
4. 🔧 **Submit PRs** - Fix bugs or add features

Please ensure your code:
- Follows existing style conventions
- Includes tests for new features
- Updates documentation as needed

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [python-gitlab](https://github.com/python-gitlab/python-gitlab)
- Email templating by [Jinja2](https://jinja.palletsprojects.com/)
- Inspired by the need for cleaner repositories everywhere! 🧹

## 💬 Support

- 📖 **Documentation**: Check the [docs](docs/) folder
- 🐛 **Issues**: [GitHub Issues](https://github.com/Re4zOon/repo-maintainer/issues)
- ❓ **Questions**: See [FAQ](docs/FAQ.md)

---

<div align="center">

**Made with ❤️ for cleaner repositories**

⭐ Star this repo if you find it helpful!

</div>
