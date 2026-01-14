# Frequently Asked Questions (FAQ)

Common questions and answers about the GitLab Stale Branch/Merge Request Notifier.

## General Questions

### What is this tool for?

This tool helps maintain a clean GitLab repository by:
- Identifying branches and merge requests that haven't been updated recently
- Notifying developers about their stale items
- Encouraging timely completion, updating, or removal of stale work

### Who should use this tool?

- **Repository maintainers** - Keep repositories clean and organized
- **Team leads** - Ensure team members complete their work
- **DevOps teams** - Automate repository maintenance
- **Organizations** - Enforce branch hygiene policies

### Does it automatically delete branches?

**No!** The tool only sends notifications. It never deletes, closes, or modifies anything in GitLab. All cleanup actions are manual and require human decision-making.

### Will it send spam to my team?

No, if configured properly:
- Each developer receives **one email** with all their stale items
- Notifications are grouped by person
- You control the frequency (schedule it weekly, bi-weekly, etc.)
- Protected branches (main, master) are automatically skipped

### Is it safe to run in production?

Yes! The tool is read-only and only sends emails. It cannot:
- Delete branches or commits
- Close merge requests
- Modify repository settings
- Change permissions

Always test with `--dry-run` first to verify behavior.

## Configuration Questions

### How do I find my GitLab project ID?

1. Navigate to your project in GitLab
2. Go to **Settings** → **General**
3. Look at the top - you'll see **Project ID: 123**

Alternatively, check the project URL:
- URL: `https://gitlab.com/username/project` → Use API to get ID
- Or look at the project's API endpoint

### What scopes does my GitLab token need?

**Minimum required**: `read_api`

This allows the tool to:
- Read project information
- List branches
- Check merge requests
- Look up user details

**Not needed**: Write access, admin permissions

### Can I monitor projects from different GitLab instances?

Not in a single config file. Create separate configuration files:

```bash
# Instance 1
python stale_branch_notifier.py -c gitlab-company.yaml

# Instance 2
python stale_branch_notifier.py -c gitlab-opensource.yaml
```

### How do I exclude certain projects?

Simply don't include them in the `projects` list. The tool only scans configured projects.

### What if I don't have an SMTP server?

You need SMTP to send emails. Options:
- **Gmail** - Free with App Passwords
- **Office 365** - If you have corporate email
- **SendGrid** - Free tier available
- **Amazon SES** - Low cost
- **Mailgun** - Free tier available

See [Setup Guide](SETUP_GUIDE.md#smtp-configuration) for details.

## Notification Questions

### Who receives the notifications?

**For merge requests:**
1. First choice: MR assignee (if active)
2. Second choice: MR author (if assignee unavailable/inactive)
3. Fallback: Configured fallback email

**For branches without MRs:**
1. First choice: Last committer (if active)
2. Fallback: Configured fallback email

See [Email Notifications Guide](EMAIL_NOTIFICATIONS.md#notification-routing-logic) for details.

### Why did someone receive a notification for someone else's branch?

This happens when:
1. Original developer's account is inactive (left company, deactivated)
2. Email goes to fallback address (usually team leads/maintainers)
3. They're the MR assignee even if not the author

Check with `--dry-run -v` to see routing decisions.

### How often should I run the notifier?

**Recommended frequencies:**

- **Weekly** - Most common, good balance
- **Bi-weekly** - For slower-moving projects
- **Daily** - Only for very active repos (may be annoying)
- **Monthly** - Too infrequent, items get very stale

**Popular schedule:** Every Monday morning

### Can I customize the email content?

Yes! Edit the `EMAIL_TEMPLATE` constant in `stale_branch_notifier.py`.

The template uses Jinja2 syntax. You can modify:
- Colors and styling (CSS)
- Text and tone
- Layout and structure
- Add your company logo

See [Email Notifications Guide](EMAIL_NOTIFICATIONS.md#customizing-emails) for examples.

### Can I send notifications to a Slack channel instead?

Not built-in, but you can add webhook support:

```python
import requests

def send_slack_notification(summary):
    webhook = "https://hooks.slack.com/services/YOUR/WEBHOOK"
    requests.post(webhook, json={
        "text": f"Found {summary['total_stale_branches']} stale branches"
    })
```

Add this to the script after email sending.

### The email went to spam. How do I fix this?

**Common causes:**
1. **SPF/DKIM not configured** - Work with IT to set up email authentication
2. **Suspicious content** - Verify your email template doesn't trigger spam filters
3. **New sending domain** - Build reputation by starting slow
4. **Email client settings** - Have users whitelist the sender

**Solutions:**
- Use company SMTP server (better reputation)
- Add sender to safe senders list
- Use professional from_email address
- Ensure proper SPF/DKIM/DMARC records

## Functionality Questions

### What makes a branch "stale"?

A branch is stale when its **last commit** is older than `stale_days` (default: 30 days).

For merge requests, staleness is based on **last update** (any activity), not the branch commit date.

### Are protected branches included?

**No!** Protected branches (main, master, develop, etc.) are automatically skipped to avoid unnecessary notifications.

### What about work-in-progress branches?

If a branch is actively being worked on (new commits within `stale_days`), it won't be flagged.

If work is truly in progress but commits are infrequent:
- Increase `stale_days` in config
- Or push periodic commits
- Or create/update an MR to show activity

### Does it check all branches?

Yes, all non-protected branches in configured projects are checked.

### What if a developer is on vacation?

The notification will wait in their inbox. If they're gone long enough that the branch becomes very stale, it will go to the fallback email if their account is deactivated.

**Best practice:** Before vacation:
- Merge completed work
- Update MR descriptions with status
- Assign MRs to someone else if needed

### Can I test without sending emails?

**Yes!** Always use `--dry-run` for testing:

```bash
python stale_branch_notifier.py --dry-run -v
```

This shows what would happen without actually sending emails.

## Technical Questions

### What Python version do I need?

**Python 3.7 or higher**

Check your version:
```bash
python --version
# or
python3 --version
```

### What are the dependencies?

```
python-gitlab >= 3.15.0
pyyaml >= 6.0
jinja2 >= 3.1.2
```

Install with:
```bash
pip install -r requirements.txt
```

### Can I run this on Windows?

Yes! Python is cross-platform. Follow the same setup steps.

For automation on Windows, use **Task Scheduler** instead of cron.

### Does it work with self-hosted GitLab?

Yes! Just configure the correct GitLab URL in `config.yaml`:

```yaml
gitlab:
  url: "https://gitlab.yourcompany.com"
```

Works with:
- GitLab CE (Community Edition)
- GitLab EE (Enterprise Edition)
- GitLab.com (SaaS)

### How long does it take to run?

Depends on:
- Number of projects
- Number of branches per project
- GitLab API response time

**Typical times:**
- 1-3 projects: < 1 minute
- 10 projects: 2-5 minutes
- 50+ projects: 10+ minutes

### Can I run multiple instances simultaneously?

Yes, but be careful:
- Each instance should use different config files
- Watch GitLab API rate limits
- Avoid overwhelming SMTP server

**Better approach:** Configure one instance to monitor all projects.

### What about API rate limits?

GitLab has rate limits (usually 600 requests/minute for authenticated users).

If you hit limits:
- Reduce number of projects
- Spread runs across different times
- Contact GitLab admin to increase limits

The tool doesn't currently implement rate limit handling.

## Troubleshooting Questions

### Error: "Configuration file not found"

**Solution:**
```bash
# Create config from example
cp config.yaml.example config.yaml

# Edit with your settings
nano config.yaml
```

### Error: "401 Unauthorized" from GitLab

**Causes:**
- Invalid or expired access token
- Token doesn't have required scopes

**Solution:**
1. Generate new token in GitLab (Settings → Access Tokens)
2. Ensure `read_api` scope is checked
3. Update token in `config.yaml`

### Error: "Failed to send email"

**Causes:**
- Wrong SMTP credentials
- Firewall blocking SMTP port
- SMTP server requires different settings

**Solution:**
1. Test SMTP connection separately (see [Setup Guide](SETUP_GUIDE.md#testing-smtp-connection))
2. Check username/password
3. Verify port (587 for TLS, 465 for SSL)
4. Try `use_tls: false` for testing (not production!)

### No stale branches found but I know there are some

**Possible causes:**
1. All branches are protected
2. `stale_days` threshold is too high
3. Projects not configured correctly

**Debug:**
```bash
python stale_branch_notifier.py --dry-run -v
```

Look for:
- "Skipping protected branch" messages
- Project connection confirmations
- Branch check details

### Emails not received

**Check:**
1. Spam/junk folder
2. Email routing rules
3. SMTP logs: `python stale_branch_notifier.py -v`
4. GitLab user email addresses are correct

**Verify:**
```bash
# Dry run to see who would receive emails
python stale_branch_notifier.py --dry-run -v | grep "Would send email"
```

### Wrong person received the email

**Why this happens:**
- MR assignee is set in GitLab
- Original committer account is inactive (fallback used)
- Email routing priority (assignee → author → fallback)

**Check routing:**
```bash
python stale_branch_notifier.py --dry-run -v
```

Look for messages like:
- "User X is not active, using fallback email"
- "MR assignee: user@example.com"

## Security Questions

### Is my GitLab token secure?

Only if you:
- ✅ Keep `config.yaml` out of version control (add to `.gitignore`)
- ✅ Use `read_api` scope only (minimum required)
- ✅ Rotate tokens periodically
- ✅ Store in environment variables for production
- ❌ Don't commit tokens to git
- ❌ Don't share config files with tokens

### Can I use environment variables for secrets?

Yes! Modify the script:

```python
import os

config['gitlab']['private_token'] = os.getenv('GITLAB_TOKEN')
config['smtp']['password'] = os.getenv('SMTP_PASSWORD')
```

Then:
```bash
export GITLAB_TOKEN="your-token"
export SMTP_PASSWORD="your-password"
python stale_branch_notifier.py
```

### What permissions does the tool need?

**GitLab:** Read-only access (`read_api` scope)
- Cannot modify, delete, or create anything
- Cannot change permissions
- Cannot access private repositories without access

**SMTP:** Send-only
- Can only send emails
- Cannot read mailboxes
- Cannot access other email accounts

### Is it safe to run from CI/CD?

Yes, but:
1. Store secrets in CI/CD variables (encrypted)
2. Use read-only GitLab tokens
3. Limit CI/CD job permissions
4. Review pipeline logs for sensitive data

## Best Practices Questions

### What's the ideal stale_days setting?

**Depends on your team:**

| Team Type | Recommended `stale_days` |
|-----------|-------------------------|
| Fast-paced startup | 14-21 days |
| Standard development | 30 days (default) |
| Enterprise/complex | 45-60 days |
| Research/experimental | 60-90 days |

Start lenient, gradually decrease as team adapts.

### Should I send to individuals or a team list?

**Best approach:** Both!

- **Active users** → Individual developers
- **Inactive users** → Team lead / fallback email (team list)

This ensures:
- Developers manage their own work
- Team leads catch items from former employees
- Nothing falls through the cracks

### How do I get team buy-in?

1. **Communicate early** - Announce before enabling
2. **Start with dry runs** - Show what would be sent
3. **Gather feedback** - Adjust based on team input
4. **Start lenient** - Higher `stale_days` initially
5. **Monitor and adjust** - Fine-tune based on results
6. **Share benefits** - Cleaner repos, easier navigation

### What metrics should I track?

- Number of stale branches (trend over time)
- Emails sent per week
- Average branch age
- Number of items cleaned up

Create monthly reports to show improvement.

## Customization Questions

### Can I change the email style?

Yes! Edit the CSS in `EMAIL_TEMPLATE`:

```python
# In stale_branch_notifier.py
EMAIL_TEMPLATE = """
<style>
    .header { 
        background: linear-gradient(135deg, #your-color-1, #your-color-2);
    }
    /* ... more CSS ... */
</style>
"""
```

### Can I add our company logo?

Yes! Add to the header:

```html
<div class="header">
    <img src="https://your-domain.com/logo.png" alt="Logo" 
         style="max-width: 150px;">
    <h1>Time for Some Spring Cleaning! ✨</h1>
</div>
```

### Can I filter by branch pattern?

Not built-in, but you can modify the code:

```python
# In get_stale_branches function, add:
if not branch.name.startswith('feature/'):
    continue  # Skip non-feature branches
```

### Can I set different thresholds per project?

Not in current version. Workaround:

```bash
# Run with different configs
python stale_branch_notifier.py -c config-team-a.yaml
python stale_branch_notifier.py -c config-team-b.yaml
```

Each config has different `stale_days` and `projects`.

## Getting Help

### Where can I report bugs?

Open an issue on GitHub: [Re4zOon/repo-maintainer](https://github.com/Re4zOon/repo-maintainer/issues)

Include:
- Error message (sanitize sensitive data!)
- Python version
- OS information
- Steps to reproduce

### Where can I request features?

Same place - GitHub Issues with label "enhancement"

### How can I contribute?

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

See `CONTRIBUTING.md` (if available) for guidelines.

### Is there a community/support channel?

Check the GitHub repository for:
- Discussions tab
- Issue tracker
- Wiki (if available)

## See Also

- [Setup Guide](SETUP_GUIDE.md) - Complete setup instructions
- [Configuration Reference](CONFIGURATION.md) - All config options  
- [Email Notifications](EMAIL_NOTIFICATIONS.md) - Email system details
- [Usage Examples](USAGE_EXAMPLES.md) - Common scenarios and examples
