# Quick Reference Guide

A cheat sheet for common tasks and commands.

## Installation (Quick)

```bash
git clone https://github.com/Re4zOon/repo-maintainer.git
cd repo-maintainer
pip install -r requirements.txt
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

## Essential Commands

```bash
# Test configuration (no emails sent)
python stale_branch_notifier.py --dry-run -v

# Send notifications
python stale_branch_notifier.py

# Use custom config
python stale_branch_notifier.py -c /path/to/config.yaml

# Verbose output
python stale_branch_notifier.py -v
```

## Configuration Checklist

- [ ] GitLab URL set correctly
- [ ] GitLab token created (with `read_api` scope)
- [ ] Project IDs added
- [ ] `stale_days` configured
- [ ] `cleanup_weeks` configured  
- [ ] Fallback email set
- [ ] SMTP server configured
- [ ] SMTP credentials tested

## GitLab Token Setup

1. GitLab → User Settings → Access Tokens
2. Name: `repo-maintainer`
3. Scopes: `read_api` ✅
4. Create token
5. Copy to `config.yaml`

## Finding Project IDs

GitLab Project → Settings → General → Project ID

## SMTP Quick Config

### Gmail
```yaml
smtp:
  host: "smtp.gmail.com"
  port: 587
  use_tls: true
  username: "your-email@gmail.com"
  password: "app-password"  # Not your regular password!
```

### Office 365
```yaml
smtp:
  host: "smtp.office365.com"
  port: 587
  use_tls: true
  username: "your-email@company.com"
  password: "your-password"
```

## Automation

### Cron (Weekly Monday 9 AM)
```bash
0 9 * * 1 cd /path/to/repo-maintainer && python stale_branch_notifier.py
```

### GitLab CI/CD
```yaml
stale-check:
  image: python:3.9
  before_script:
    - pip install -r requirements.txt
  script:
    - python stale_branch_notifier.py
  only:
    - schedules
```

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| Config not found | `cp config.yaml.example config.yaml` |
| GitLab 401 error | Check token, regenerate if needed |
| SMTP auth failed | Use app password (Gmail), check credentials |
| No stale branches | Lower `stale_days` or check project IDs |
| Email in spam | Whitelist sender, check SPF/DKIM |

## Email Template Customization

Edit `EMAIL_TEMPLATE` in `stale_branch_notifier.py`:

```python
# Change header color
.header { 
    background: linear-gradient(135deg, #YOUR-COLOR-1, #YOUR-COLOR-2);
}

# Change greeting
<p>Your Custom Greeting Here! 👋</p>

# Add logo
<img src="https://your-site.com/logo.png" style="max-width: 150px;">
```

## Common Config Values

| Setting | Conservative | Standard | Aggressive |
|---------|-------------|----------|------------|
| `stale_days` | 60 | 30 | 14 |
| `cleanup_weeks` | 8 | 4 | 2 |

## Testing Workflow

1. ✅ Create config: `cp config.yaml.example config.yaml`
2. ✅ Edit config with real values
3. ✅ Test SMTP: Use test script from docs
4. ✅ Dry run: `python stale_branch_notifier.py --dry-run -v`
5. ✅ Review output
6. ✅ Send test: Run without dry-run
7. ✅ Check inbox
8. ✅ Set up automation

## API Rate Limits

**GitLab.com**: ~600 requests/minute

**Estimated usage**:
- 1 auth call
- 2 calls per project (details + branches)
- 1 call per stale branch (MR check)
- 1 call per unique user (status check)

**Example**: 10 projects, 50 stale branches = ~150 calls

## Important Files

| File | Purpose |
|------|---------|
| `config.yaml` | Your configuration (don't commit!) |
| `stale_branch_notifier.py` | Main script |
| `requirements.txt` | Dependencies |
| `docs/` | Documentation |
| `tests/` | Unit tests |

## Environment Variables (Optional)

```bash
export GITLAB_TOKEN="your-token"
export SMTP_PASSWORD="your-password"

# Then in script, load from environment
config['gitlab']['private_token'] = os.getenv('GITLAB_TOKEN')
```

## Email Routing Priority

**For Merge Requests:**
1. Assignee (if active) ✅
2. Author (if active) ✅
3. Fallback email ✅

**For Branches:**
1. Last committer (if active) ✅
2. Fallback email ✅

## Success Indicators

After running, you should see:
```
Total stale branches found: X
Total stale merge requests found: Y
Emails sent: Z
Emails failed: 0
Recipients: user1@example.com, user2@example.com
```

## Getting Help

1. Check [FAQ](FAQ.md)
2. Review [Setup Guide](SETUP_GUIDE.md)
3. Run with `-v` for details
4. Check error messages
5. Open GitHub issue

## Security Checklist

- [ ] `.gitignore` includes `config.yaml`
- [ ] Token has minimal scope (`read_api` only)
- [ ] Config file has restricted permissions
- [ ] SMTP credentials are secure
- [ ] Using TLS for SMTP
- [ ] Rotate tokens periodically

## Performance Tips

- Start with fewer projects, add more later
- Run during off-hours (less API load)
- Use caching for large installations
- Monitor API rate limits
- Schedule weekly, not daily (for most teams)

## Documentation Links

- 📘 [Setup Guide](SETUP_GUIDE.md) - Detailed setup
- 📧 [Email Guide](EMAIL_NOTIFICATIONS.md) - Email details
- 📸 [Screenshots](SCREENSHOTS.md) - Visual examples
- ⚙️ [Config Reference](CONFIGURATION.md) - All options
- 💻 [Usage Examples](USAGE_EXAMPLES.md) - Real scenarios
- 🏗️ [Architecture](ARCHITECTURE.md) - How it works
- ❓ [FAQ](FAQ.md) - Common questions

## Quick Wins

1. **Start lenient**: Set `stale_days: 60` initially
2. **Test first**: Always use `--dry-run`
3. **Monitor**: Check logs for first few runs
4. **Adjust**: Fine-tune based on feedback
5. **Automate**: Set up weekly cron job
6. **Celebrate**: Watch your repo get cleaner! 🎉
