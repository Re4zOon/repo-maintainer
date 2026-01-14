# Email Notifications Guide

This document explains how the email notification system works, including examples, routing logic, and customization options.

## Table of Contents

- [Overview](#overview)
- [Email Template Example](#email-template-example)
- [Notification Routing Logic](#notification-routing-logic)
- [Email Content Details](#email-content-details)
- [Customizing Emails](#customizing-emails)
- [Best Practices](#best-practices)

## Overview

The stale branch notifier sends **friendly, actionable email notifications** to developers when their branches or merge requests become stale (inactive for a configured number of days).

### Key Features

- 🎨 **Beautiful HTML emails** with modern, responsive design
- 😄 **Friendly and slightly humorous tone** to make notifications less intimidating
- 📊 **Grouped notifications** - one email per developer with all their stale items
- 🔀 **Smart routing** - notifications go to the right person based on context
- 📱 **Mobile-friendly** design that looks good on all devices

## Email Template Example

Here's what a notification email looks like:

```
┌─────────────────────────────────────────────────────────┐
│  🧹 Time for Some Spring Cleaning! ✨                   │
│  (Orange gradient header)                               │
└─────────────────────────────────────────────────────────┘

Hey there, Code Gardener! 👋

┌─────────────────────────────────────────────────────────┐
│ 🕰️ Whoops! It looks like some of your branches and     │
│ merge requests have been gathering dust (over 30 days   │
│ of inactivity). Don't worry, we're not judging...       │
│ much. 😉                                                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 🔀 Merge Requests That Need Some Love             [2]   │
│                                                          │
│ These MRs have been waiting patiently for your          │
│ attention:                                               │
│                                                          │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 📂 my-awesome-project                               │ │
│ │ !42 - Add new feature for user authentication       │ │
│ │ 🌿 Branch: feature/auth-system                      │ │
│ │ 🕒 Last updated: 2024-12-15 14:30:00 by Jane Doe   │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                          │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 📂 backend-api                                      │ │
│ │ !15 - Fix memory leak in worker process            │ │
│ │ 🌿 Branch: bugfix/memory-leak                       │ │
│ │ 🕒 Last updated: 2024-12-10 09:15:00 by Jane Doe   │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 🌳 Lonely Branches                                  [1] │
│                                                          │
│ These branches are feeling a bit neglected:             │
│                                                          │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 📂 frontend-app                                     │ │
│ │ experimental/new-ui                                 │ │
│ │ 🕒 Last commit: 2024-12-01 16:45:00 by Jane Doe    │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 🎯 What Can You Do?                                     │
│                                                          │
│ Pick your adventure:                                     │
│                                                          │
│ ✅ Merge it - If the work is done, give it the green   │
│    light!                                                │
│ 🔄 Update it - Still working on it? Push some fresh    │
│    commits!                                              │
│ ❌ Close/Delete it - No longer needed? Let's declutter! │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ ⏰ Tick-Tock Alert!                                     │
│ If these items continue hibernating, they'll be         │
│ automatically cleaned up in 4 weeks. No pressure,       │
│ but... actually, yes, a little pressure. 😅             │
└─────────────────────────────────────────────────────────┘

Questions? Concerns? Existential dread about your 
branches? Feel free to reach out to the repository 
maintainers—we're here to help!

──────────────────────────────────────────────────────────
Happy Coding! 🚀
The GitLab Repository Maintenance Bot

💡 Pro tip: A clean repository is a happy repository! 
   (And it makes your teammates happy too!)
──────────────────────────────────────────────────────────
```

## Notification Routing Logic

Understanding who receives notifications and why:

### For Merge Requests (MRs)

When a stale branch has an **open merge request**, the notification follows this priority:

```
1. MR Assignee (if assigned and active)
   └─► Check if user is active in GitLab
       ├─► Yes: Send to assignee
       └─► No: Try next option

2. MR Author (if assignee unavailable/inactive)
   └─► Check if user is active in GitLab
       ├─► Yes: Send to author
       └─► No: Try next option

3. Fallback Email (if both unavailable/inactive)
   └─► Send to configured fallback email
       (usually repo-maintainers@example.com)
```

**Example Scenario:**
```
MR !42: "Add authentication feature"
├─ Assignee: john@example.com (Active) ✅
├─ Author: jane@example.com
└─ 📧 Notification sent to: john@example.com
```

**Example Scenario with Inactive User:**
```
MR !15: "Fix critical bug"
├─ Assignee: bob@example.com (Inactive - left company) ❌
├─ Author: alice@example.com (Active) ✅
└─ 📧 Notification sent to: alice@example.com
```

### For Branches (Without MRs)

When a stale branch has **no open merge request**, the notification goes to:

```
1. Branch Committer (last person to commit)
   └─► Check if user is active in GitLab
       ├─► Yes: Send to committer
       └─► No: Try fallback

2. Fallback Email (if committer inactive)
   └─► Send to configured fallback email
```

**Example Scenario:**
```
Branch: feature/experimental-ui
├─ Last committer: sarah@example.com (Active) ✅
└─ 📧 Notification sent to: sarah@example.com
```

### Active User Detection

A user is considered **active** if:
- Their GitLab account exists
- Their account status is "active" (not blocked, deactivated, or deleted)

This prevents sending emails to:
- Former employees who left the company
- Deactivated accounts
- Blocked users

### Fallback Email

The `fallback_email` in your configuration is used when:
- User account is inactive/deactivated
- Email address cannot be determined
- MR has no assignee or author information

**Best Practice**: Set `fallback_email` to a team mailing list or repository maintainers group.

## Email Content Details

### Email Subject Line

The subject varies based on content:

| Content Type | Subject Example |
|-------------|----------------|
| Both MRs and Branches | `[Action Required] 5 Stale Item(s) Require Attention` |
| Only MRs | `[Action Required] 3 Stale Merge Request(s) Require Attention` |
| Only Branches | `[Action Required] 2 Stale Branch(es) Require Attention` |

### Information Included

For **Merge Requests**, each item shows:
- 📂 **Project name**: Which repository the MR belongs to
- 🔗 **MR link**: Direct link to the merge request (clickable)
- 📝 **MR title**: Description of the merge request
- 🌿 **Source branch**: The branch name
- 🕒 **Last updated**: When the MR was last modified and by whom

For **Branches**, each item shows:
- 📂 **Project name**: Which repository the branch belongs to
- 🏷️ **Branch name**: The full branch name
- 🕒 **Last commit**: When the last commit was made and by whom

### Action Items

The email clearly explains three options:
1. ✅ **Merge** - Complete the work and merge the changes
2. 🔄 **Update** - Continue working and push new commits
3. ❌ **Close/Delete** - Remove if no longer needed

### Warning Notice

A clear warning indicates:
- ⏰ **Timeline**: How many weeks until automatic cleanup
- 🎯 **Action needed**: Items need attention to avoid deletion

## Customizing Emails

### Changing the Tone

You can modify the email template in `stale_branch_notifier.py`. Look for the `EMAIL_TEMPLATE` constant.

To make it more **formal**:
```html
<div class="greeting">
    <p>Dear Team Member,</p>
</div>

<div class="intro">
    <p><strong>Notification:</strong> The following items require your attention
    as they have been inactive for {{ stale_days }} days.</p>
</div>
```

To make it more **fun**:
```html
<div class="greeting">
    <p>Greetings, Code Warrior! ⚔️</p>
</div>

<div class="intro">
    <p><strong>🚨 Red Alert!</strong> Your branches have been napping for 
    {{ stale_days }} days! Time to wake them up! ☕</p>
</div>
```

### Changing Colors

Modify the CSS in the `<style>` section:

```css
/* Change header gradient */
.header { 
    background: linear-gradient(135deg, #6a11cb 0%, #2575fc 100%);
}

/* Change warning box color */
.warning { 
    background-color: #fff3cd;
    border-left: 4px solid #ffc107;
}
```

### Adding Your Logo

Add an image in the header:

```html
<div class="header">
    <img src="https://your-domain.com/logo.png" alt="Company Logo" 
         style="max-width: 150px; margin-bottom: 15px;">
    <h1>Time for Some Spring Cleaning! ✨</h1>
</div>
```

### Adding Footer Links

Customize the footer:

```html
<div class="footer">
    <p><strong>Happy Coding! 🚀</strong></p>
    <p>The GitLab Repository Maintenance Bot</p>
    <p style="margin-top: 15px;">
        <a href="https://wiki.company.com/git-guidelines">Git Guidelines</a> |
        <a href="https://wiki.company.com/branch-policy">Branch Policy</a> |
        <a href="mailto:devops@company.com">Contact DevOps</a>
    </p>
</div>
```

## Best Practices

### 1. Set Appropriate Stale Thresholds

Choose `stale_days` based on your team's workflow:

- **Fast-paced teams**: 14-21 days
- **Normal development**: 30 days (default)
- **Long-term projects**: 45-60 days

### 2. Configure Cleanup Warnings Wisely

Set `cleanup_weeks` to give developers enough time:

- After first notification: 4 weeks (default)
- For critical projects: 6-8 weeks
- For experimental repos: 2-3 weeks

### 3. Use Team Email for Fallback

Instead of a single person:
```yaml
fallback_email: "dev-team@company.com"
```

Benefits:
- Distributes responsibility
- Ensures someone will see it
- Works across time zones

### 4. Schedule Regular Runs

Run the notifier weekly or bi-weekly:

```bash
# Weekly on Monday mornings
0 9 * * 1 /path/to/python /path/to/stale_branch_notifier.py
```

This creates a consistent reminder rhythm without overwhelming developers.

### 5. Test Before Going Live

Always test with `--dry-run` first:

```bash
# Check what would be sent
python stale_branch_notifier.py --dry-run -v

# Verify output, then run for real
python stale_branch_notifier.py
```

### 6. Monitor Delivery

Check your logs regularly:
```bash
# Run with verbose logging
python stale_branch_notifier.py -v > notification.log 2>&1

# Review the summary
tail -20 notification.log
```

### 7. Communicate with Your Team

Before enabling automated notifications:
1. Announce the new system
2. Explain the purpose and benefits
3. Share documentation links
4. Do a trial run with volunteers
5. Gather feedback and adjust

## Troubleshooting Notifications

### Email Not Received

**Check:**
1. Spam/junk folder
2. Email routing rules
3. SMTP logs (run with `-v`)
4. User's GitLab email address is correct

### Wrong Person Received Email

**Possible causes:**
1. MR assignee is set incorrectly in GitLab
2. Branch committer email doesn't match GitLab profile
3. Fallback email being used due to inactive users

**Solution:**
- Review GitLab MR assignments
- Check user activity status
- Run with `--dry-run -v` to see routing decisions

### Email Looks Broken

**Possible causes:**
1. Email client doesn't support HTML
2. Corporate email filters stripping HTML
3. Template rendering error

**Solution:**
- Test with different email clients
- Check Jinja2 template syntax
- Validate HTML with online validators

## Example Notifications

### Scenario 1: New Developer with Stale Feature Branch

**Context**: Sarah created a feature branch 35 days ago but hasn't worked on it.

**Email received by**: sarah@company.com

**Content**:
- 1 stale branch: `feature/user-profile-redesign`
- No merge requests
- Action: Either continue work, create MR, or delete if abandoned

### Scenario 2: Forgotten Merge Request

**Context**: PR !123 was created by John, assigned to Alice, but no activity for 40 days.

**Email received by**: alice@company.com (assignee)

**Content**:
- 1 stale MR: !123 "Implement caching layer"
- Branch: `feature/redis-cache`
- Action: Review and merge, or reassign if unable to review

### Scenario 3: Team Lead Cleanup

**Context**: Multiple stale items from inactive developers.

**Email received by**: team-leads@company.com (fallback email)

**Content**:
- 5 stale branches from ex-employees
- 2 stale MRs with no assignee
- Action: Team lead reviews and decides on each item

## Next Steps

- Review the [Configuration Reference](CONFIGURATION.md) for all available options
- Check [Usage Examples](USAGE_EXAMPLES.md) for command-line tips
- See [FAQ](FAQ.md) for common questions
