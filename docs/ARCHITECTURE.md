# Architecture and Workflow

This document explains the technical architecture and workflow of the GitLab Stale Branch Notifier.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Stale Branch Notifier                     │
│                      (Python Script)                         │
└─────────────────────────────────────────────────────────────┘
                             │
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    ┌─────────┐         ┌─────────┐       ┌──────────┐
    │ GitLab  │         │  YAML   │       │   SMTP   │
    │   API   │         │ Config  │       │  Server  │
    │         │         │  File   │       │          │
    └─────────┘         └─────────┘       └──────────┘
         │                                       │
         │ Read projects,                        │ Send
         │ branches, MRs                         │ emails
         │                                       │
         ▼                                       ▼
    ┌─────────────┐                      ┌──────────────┐
    │   Project   │                      │ Developers   │
    │  Metadata   │                      │ & Maintainer │
    └─────────────┘                      └──────────────┘
```

## Component Overview

### 1. Configuration Loader
- **File**: `stale_branch_notifier.py` (functions: `load_config`, `validate_config`)
- **Purpose**: Load and validate YAML configuration
- **Input**: `config.yaml` file
- **Output**: Validated configuration dictionary

### 2. GitLab Client
- **File**: `stale_branch_notifier.py` (function: `create_gitlab_client`)
- **Library**: `python-gitlab`
- **Purpose**: Interface with GitLab REST API
- **Authentication**: Private token with `read_api` scope

### 3. Branch Analyzer
- **File**: `stale_branch_notifier.py` (function: `get_stale_branches`)
- **Purpose**: Identify branches that haven't been updated recently
- **Logic**:
  - Fetch all branches from project
  - Skip protected branches
  - Compare last commit date to threshold
  - Return stale branch details

### 4. MR Detector
- **File**: `stale_branch_notifier.py` (function: `get_merge_request_for_branch`)
- **Purpose**: Find open merge requests for stale branches
- **Logic**:
  - Search for MRs with matching source branch
  - Filter by state (only 'opened')
  - Extract MR metadata (assignee, author, update time)

### 5. Email Router
- **File**: `stale_branch_notifier.py` (functions: `get_mr_notification_email`, `get_notification_email`)
- **Purpose**: Determine correct recipient for each notification
- **Logic**:
  - For MRs: assignee → author → fallback
  - For branches: committer → fallback
  - Verify user is active in GitLab
  - Use fallback email if user inactive

### 6. Email Generator
- **File**: `stale_branch_notifier.py` (function: `generate_email_content`)
- **Template Engine**: Jinja2
- **Purpose**: Create beautiful HTML emails
- **Input**: Branches, MRs, configuration
- **Output**: Rendered HTML email

### 7. Email Sender
- **File**: `stale_branch_notifier.py` (function: `send_email`)
- **Library**: `smtplib`
- **Purpose**: Deliver notifications via SMTP
- **Features**: TLS support, authentication, error handling

## Detailed Workflow

### Phase 1: Initialization

```
START
  │
  ├─► Parse command-line arguments
  │   ├─ Config file path (-c)
  │   ├─ Dry-run mode (--dry-run)
  │   └─ Verbose logging (-v)
  │
  ├─► Load configuration file
  │   ├─ Read YAML file
  │   ├─ Validate required fields
  │   └─ Check SMTP/GitLab settings
  │
  └─► Create GitLab client
      ├─ Connect to GitLab API
      ├─ Authenticate with token
      └─ Verify connection
```

### Phase 2: Data Collection

```
FOR EACH project in configured projects:
  │
  ├─► Fetch project metadata
  │   └─ Project name, ID, settings
  │
  ├─► Get all branches
  │   ├─ API call: GET /projects/:id/branches
  │   └─ Fetch protected branches list
  │
  ├─► Filter branches
  │   ├─ Skip if protected (main, master, etc.)
  │   └─ Skip if recent activity (< stale_days)
  │
  └─► FOR EACH stale branch:
      │
      ├─► Parse commit metadata
      │   ├─ Last commit date
      │   ├─ Committer email
      │   └─ Author name
      │
      └─► Check for open MR
          ├─ API call: GET /projects/:id/merge_requests
          │            ?source_branch=:name&state=opened
          │
          ├─► IF MR exists:
          │   ├─ Extract MR details
          │   │  ├─ Assignee info
          │   │  ├─ Author info
          │   │  └─ Last update time
          │   │
          │   └─ Check MR staleness
          │      ├─ Compare update time to threshold
          │      └─ Add to MR list if stale
          │
          └─► ELSE:
              └─ Add to branch-only list
```

### Phase 3: Email Routing

```
Initialize email_to_items map {}

FOR EACH stale item (branch or MR):
  │
  ├─► Determine recipient email
  │   │
  │   ├─► IF item is MR:
  │   │   │
  │   │   ├─► Get assignee email
  │   │   │   ├─ Check if assignee exists
  │   │   │   └─ Verify user is active
  │   │   │
  │   │   ├─► IF assignee unavailable:
  │   │   │   ├─ Get author email
  │   │   │   └─ Verify user is active
  │   │   │
  │   │   └─► IF author unavailable:
  │   │       └─ Use fallback email
  │   │
  │   └─► IF item is branch:
  │       │
  │       ├─► Get committer email
  │       │   └─ Verify user is active
  │       │
  │       └─► IF committer unavailable:
  │           └─ Use fallback email
  │
  └─► Group by recipient
      └─ email_to_items[recipient].append(item)
```

### Phase 4: Notification Generation

```
FOR EACH (recipient_email, items) in email_to_items:
  │
  ├─► Separate items into:
  │   ├─ merge_requests[]
  │   └─ branches[]
  │
  ├─► Generate email content
  │   ├─ Load Jinja2 template
  │   ├─ Render with data:
  │   │  ├─ merge_requests
  │   │  ├─ branches
  │   │  ├─ stale_days
  │   │  └─ cleanup_weeks
  │   └─ Output HTML string
  │
  ├─► Create subject line
  │   ├─ IF both MRs and branches:
  │   │   └─ "[Action Required] N Stale Item(s)..."
  │   ├─ IF only MRs:
  │   │   └─ "[Action Required] N Stale MR(s)..."
  │   └─ IF only branches:
  │       └─ "[Action Required] N Stale Branch(es)..."
  │
  └─► Build MIME message
      ├─ Set headers (From, To, Subject)
      ├─ Attach HTML content
      └─ Ready for sending
```

### Phase 5: Email Delivery

```
FOR EACH email message:
  │
  ├─► IF dry-run mode:
  │   ├─ Log: "[DRY RUN] Would send email to: {email}"
  │   └─ Skip actual sending
  │
  └─► ELSE:
      │
      ├─► Connect to SMTP server
      │   ├─ Host: smtp.host
      │   └─ Port: smtp.port
      │
      ├─► IF use_tls:
      │   └─ Enable TLS encryption
      │
      ├─► Authenticate
      │   ├─ Username: smtp.username
      │   └─ Password: smtp.password
      │
      ├─► Send message
      │   └─ SMTP.send_message()
      │
      ├─► Log result
      │   ├─ Success: "Email sent to {email}"
      │   └─ Failure: "Failed to send to {email}: {error}"
      │
      └─► Update summary
          ├─ Increment emails_sent or emails_failed
          └─ Add to recipients list
```

### Phase 6: Summary & Cleanup

```
Generate summary report:
  ├─ Total stale branches found
  ├─ Total stale merge requests found
  ├─ Emails sent successfully
  ├─ Emails failed
  └─ List of recipients

Log summary to console

Return exit code:
  ├─ 0 = Success
  └─ 1 = Error (config, connection, etc.)

END
```

## Data Structures

### Stale Branch Object

```python
{
    'project_id': 123,
    'project_name': 'my-awesome-project',
    'branch_name': 'feature/new-ui',
    'last_commit_date': '2024-01-15 14:30:00',
    'author_name': 'John Doe',
    'author_email': 'john@example.com',
    'committer_email': 'john@example.com'
}
```

### Stale MR Object

```python
{
    'iid': 42,
    'title': 'Add authentication system',
    'web_url': 'https://gitlab.com/project/merge_requests/42',
    'branch_name': 'feature/auth-system',
    'project_id': 123,
    'project_name': 'my-awesome-project',
    'assignee_email': 'alice@example.com',
    'assignee_username': 'alice',
    'author_email': 'bob@example.com',
    'author_name': 'Bob Smith',
    'author_username': 'bob',
    'last_updated': '2024-01-15 14:30:00',
    'updated_at': datetime(2024, 1, 15, 14, 30, 0)
}
```

### Email-to-Items Map

```python
{
    'alice@example.com': {
        'branches': [branch1, branch2],
        'merge_requests': [mr1, mr2]
    },
    'bob@example.com': {
        'branches': [branch3],
        'merge_requests': []
    },
    'fallback@example.com': {
        'branches': [branch4],
        'merge_requests': [mr3]
    }
}
```

## API Calls

### GitLab API Endpoints Used

| Endpoint | Purpose | Rate Impact |
|----------|---------|-------------|
| `GET /api/v4/user` | Authenticate connection | 1 call |
| `GET /api/v4/projects/:id` | Get project details | 1 per project |
| `GET /api/v4/projects/:id/branches` | List branches | 1+ per project* |
| `GET /api/v4/projects/:id/protected_branches` | List protected branches | 1+ per project* |
| `GET /api/v4/projects/:id/merge_requests` | Find MRs for branches | 1 per stale branch |
| `GET /api/v4/users` | Look up user by email/username | 1+ per unique user |

*May require pagination for large projects

### API Rate Limits

- **GitLab.com**: 600 requests/minute (authenticated)
- **Self-hosted**: Usually higher, check with admin

**Estimate total calls:**
```
1 (auth) 
+ N_projects × 2 (project details + branches)
+ N_stale_branches (MR lookups)
+ N_unique_users (user status checks)
≈ 1 + 2N + B + U calls
```

## Performance Considerations

### Typical Execution Times

| Projects | Branches | Stale Items | Time |
|----------|----------|-------------|------|
| 1-3 | < 100 | < 10 | < 30s |
| 5-10 | 100-500 | 10-50 | 1-3 min |
| 20+ | 500+ | 50+ | 5-10 min |

### Optimization Opportunities

1. **Caching**
   - Cache user status lookups
   - Cache project metadata
   - Reduce duplicate API calls

2. **Parallel Processing**
   - Process projects concurrently
   - Batch MR lookups
   - Parallel user lookups

3. **Pagination**
   - Implement efficient pagination
   - Use `per_page=100` for API calls
   - Handle large repositories better

4. **Filtering**
   - Early filtering of protected branches
   - Skip projects with no recent activity
   - Configurable branch patterns

## Security Model

### Read-Only Access

The tool **cannot**:
- ❌ Delete branches
- ❌ Close merge requests
- ❌ Modify commits
- ❌ Change permissions
- ❌ Access private repos without permission

### Required Permissions

**GitLab Token:**
- ✅ `read_api` scope (minimum)
- ❌ No write access needed

**SMTP:**
- ✅ Send email only
- ❌ No read access to mailboxes

### Secret Management

**Sensitive data:**
- GitLab private token
- SMTP password

**Best practices:**
1. Use environment variables
2. Keep config files out of git (`.gitignore`)
3. Rotate tokens periodically
4. Use app-specific passwords (Gmail)
5. Encrypt configs at rest (production)

## Error Handling

### Graceful Degradation

```
Error occurs → Log error → Continue with next item
```

**Examples:**
- GitLab API error → Skip project, continue
- SMTP error → Log failure, try next email
- Invalid date format → Skip branch, log warning
- User lookup fails → Use fallback email

### Error Categories

1. **Configuration Errors** (fatal)
   - Missing config file → Exit with error
   - Invalid YAML → Exit with error
   - Missing required fields → Exit with error

2. **Connection Errors** (retryable)
   - GitLab connection failed → Retry or exit
   - SMTP connection failed → Log and continue

3. **Data Errors** (skip)
   - Invalid commit date → Skip branch
   - MR lookup failed → Treat as no MR
   - User not found → Use fallback

4. **Email Errors** (log)
   - Send failed → Log, increment counter
   - Invalid recipient → Log warning

## Testing Strategy

### Unit Tests

Test individual functions:
- Configuration validation
- Date parsing
- Email routing logic
- Template rendering

### Integration Tests

Test component interaction:
- GitLab API mocking
- SMTP server mocking
- End-to-end flow

### Manual Testing

Use dry-run mode:
```bash
python stale_branch_notifier.py --dry-run -v
```

Validates:
- Configuration correctness
- API connectivity
- Email routing decisions
- No actual emails sent

## Extending the Tool

### Adding New Features

**Common extensions:**

1. **Webhook notifications** (Slack, Teams)
   ```python
   def send_webhook(url, data):
       requests.post(url, json=data)
   ```

2. **Multiple notification methods**
   ```python
   if config.get('slack_webhook'):
       send_slack_notification()
   if config.get('smtp'):
       send_email_notification()
   ```

3. **Custom branch filters**
   ```python
   def should_process_branch(branch):
       if branch.startswith('hotfix/'):
           return False  # Never flag hotfix branches
       return True
   ```

4. **Metrics export**
   ```python
   def export_metrics(summary):
       # Export to Prometheus, StatsD, etc.
       metrics.gauge('stale_branches', summary['total_stale_branches'])
   ```

### Plugin Architecture

Future enhancement: Plugin system for custom logic

```python
# plugins/custom_filter.py
class BranchFilter:
    def should_notify(self, branch):
        # Custom logic
        return True

# Load and use plugins
for plugin in load_plugins():
    if not plugin.should_notify(branch):
        continue
```

## See Also

- [Setup Guide](SETUP_GUIDE.md) - Installation and configuration
- [Configuration Reference](CONFIGURATION.md) - All config options
- [Usage Examples](USAGE_EXAMPLES.md) - Common scenarios
- [FAQ](FAQ.md) - Frequently asked questions
