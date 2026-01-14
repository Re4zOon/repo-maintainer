#!/usr/bin/env python3
"""
GitLab Stale Branch/Merge Request Notifier

This script identifies stale branches in GitLab projects and sends
email notifications to their committers about upcoming cleanup.
If a merge request exists for a stale branch, it notifies about the MR instead.
"""

import argparse
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import gitlab
import yaml
from jinja2 import Template


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; }
        .header { background-color: #fc6d26; color: white; padding: 20px; }
        .content { padding: 20px; }
        .branch-list { background-color: #f5f5f5; padding: 15px; margin: 10px 0; }
        .warning { color: #d93025; font-weight: bold; }
        .branch-item { margin: 5px 0; }
        .mr-item { margin: 5px 0; background-color: #e8f4e8; padding: 10px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>GitLab Branch Cleanup Notification</h1>
    </div>
    <div class="content">
        <p>Hello,</p>

        <p>The following items in our GitLab projects have been identified as stale
        (no activity in the last {{ stale_days }} days) and require your attention:</p>

        {% if merge_requests %}
        <div class="branch-list">
            <h3>Stale Merge Requests:</h3>
            {% for mr in merge_requests %}
            <div class="mr-item">
                <strong>{{ mr.project_name }}</strong>: <a href="{{ mr.web_url }}">!{{ mr.iid }} - {{ mr.title }}</a>
                <br>
                <small>Source branch: <code>{{ mr.branch_name }}</code></small>
                <br>
                <small>Last updated: {{ mr.last_updated }} by {{ mr.author_name }}</small>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if branches %}
        <div class="branch-list">
            <h3>Stale Branches:</h3>
            {% for branch in branches %}
            <div class="branch-item">
                <strong>{{ branch.project_name }}</strong>: <code>{{ branch.branch_name }}</code>
                <br>
                <small>Last commit: {{ branch.last_commit_date }} by {{ branch.author_name }}</small>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        <p><strong>Action Required:</strong> Please review these items and either:</p>
        <ul>
            <li>Merge them if the work is complete</li>
            <li>Update them with new commits if work is ongoing</li>
            <li>Close/Delete them if they are no longer needed</li>
        </ul>

        <p class="warning">⚠️ Important: Items that remain inactive will be automatically
        cleaned up after {{ cleanup_weeks }} weeks from this notification.</p>

        <p>If you have any questions, please contact the repository maintainers.</p>

        <p>Best regards,<br>GitLab Repository Maintenance Team</p>
    </div>
</body>
</html>
"""


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required fields."""


def validate_config(config: dict) -> None:
    """
    Validate that all required configuration keys are present.

    Args:
        config: Configuration dictionary to validate

    Raises:
        ConfigurationError: If required keys are missing
    """
    required_gitlab_keys = ['url', 'private_token']
    required_smtp_keys = ['host', 'port', 'from_email']

    if not config:
        raise ConfigurationError("Configuration is empty")

    if 'gitlab' not in config:
        raise ConfigurationError("Missing 'gitlab' section in configuration")

    for key in required_gitlab_keys:
        if key not in config['gitlab']:
            raise ConfigurationError(f"Missing required GitLab config key: '{key}'")

    if 'smtp' not in config:
        raise ConfigurationError("Missing 'smtp' section in configuration")

    for key in required_smtp_keys:
        if key not in config['smtp']:
            raise ConfigurationError(f"Missing required SMTP config key: '{key}'")

    if not config.get('projects'):
        raise ConfigurationError("No projects configured. Add project IDs to 'projects' list.")

    if not config.get('fallback_email'):
        logger.warning(
            "No fallback_email configured. Branches from inactive users will be skipped."
        )


def load_config(config_path: str) -> dict:
    """Load and validate configuration from a YAML file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    validate_config(config)
    return config


def create_gitlab_client(config: dict) -> gitlab.Gitlab:
    """Create and authenticate a GitLab client."""
    gl = gitlab.Gitlab(
        url=config['gitlab']['url'],
        private_token=config['gitlab']['private_token']
    )
    gl.auth()
    return gl


def parse_commit_date(date_str: str) -> datetime:
    """
    Parse a commit date string into a datetime object.

    Handles various ISO 8601 formats that GitLab might return.

    Args:
        date_str: Date string in ISO 8601 format

    Returns:
        datetime object with timezone info

    Raises:
        ValueError: If the date cannot be parsed
    """
    # Handle 'Z' suffix (UTC)
    if date_str.endswith('Z'):
        date_str = date_str[:-1] + '+00:00'

    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        # Try parsing without microseconds
        formats = [
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%d %H:%M:%S%z',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Unable to parse date: {date_str}")


def get_stale_branches(gl: gitlab.Gitlab, project_id: int, stale_days: int) -> list:
    """
    Get branches from a project where the last commit is older than stale_days.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        stale_days: Number of days after which a branch is considered stale

    Returns:
        List of stale branch information dictionaries
    """
    project = gl.projects.get(project_id)
    stale_branches = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)

    protected_branches = {pb.name for pb in project.protectedbranches.list(all=True)}

    for branch in project.branches.list(all=True):
        if branch.name in protected_branches:
            logger.debug(f"Skipping protected branch: {branch.name}")
            continue

        commit = branch.commit
        commit_date_str = commit['committed_date']

        try:
            commit_date = parse_commit_date(commit_date_str)
        except ValueError as e:
            logger.warning(
                f"Could not parse commit date for branch {branch.name}: {e}. Skipping."
            )
            continue

        if commit_date < cutoff_date:
            stale_branches.append({
                'project_id': project_id,
                'project_name': project.name,
                'branch_name': branch.name,
                'last_commit_date': commit_date.strftime('%Y-%m-%d %H:%M:%S'),
                'author_name': commit.get('author_name', 'Unknown'),
                'author_email': commit.get('author_email', ''),
                'committer_email': commit.get('committer_email', ''),
            })

    return stale_branches


def _get_email_from_gitlab_object(obj: dict) -> str:
    """
    Extract email from a GitLab user object (assignee or author).

    Args:
        obj: GitLab user object dictionary

    Returns:
        Email address or empty string if not found
    """
    if isinstance(obj, dict):
        return obj.get('email', '')
    return ''


def get_merge_request_for_branch(project, branch_name: str) -> Optional[dict]:
    """
    Get an open merge request for the given branch, if one exists.

    Args:
        project: GitLab project object
        branch_name: Name of the source branch

    Returns:
        Dictionary with MR information if found, None otherwise
    """
    try:
        mrs = project.mergerequests.list(
            source_branch=branch_name,
            state='opened',
            per_page=1
        )
        if mrs:
            mr = mrs[0]
            # Get assignee email if available, otherwise use author
            assignee_email = ''
            author_email = ''
            author_username = ''

            if hasattr(mr, 'assignee') and mr.assignee:
                assignee_email = _get_email_from_gitlab_object(mr.assignee)
            if hasattr(mr, 'author') and mr.author:
                author_email = _get_email_from_gitlab_object(mr.author)
                if isinstance(mr.author, dict):
                    author_username = mr.author.get('username', '')

            # Parse updated_at date for display
            updated_at = mr.updated_at
            try:
                updated_date = parse_commit_date(updated_at)
                last_updated = updated_date.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                last_updated = updated_at

            return {
                'iid': mr.iid,
                'title': mr.title,
                'web_url': mr.web_url,
                'branch_name': branch_name,
                'project_id': project.id,
                'project_name': project.name,
                'assignee_email': assignee_email,
                'author_email': author_email,
                'author_name': mr.author.get('name', 'Unknown') if hasattr(mr, 'author') and mr.author else 'Unknown',
                'author_username': author_username,
                'last_updated': last_updated,
            }
    except gitlab.exceptions.GitlabError as e:
        logger.warning(f"Error fetching merge requests for branch {branch_name}: {e}")
    return None


def get_user_email_by_username(gl: gitlab.Gitlab, username: str) -> str:
    """
    Get a user's email by their username.

    Args:
        gl: Authenticated GitLab client
        username: GitLab username

    Returns:
        User's email address or empty string if not found
    """
    try:
        users = gl.users.list(username=username, per_page=1)
        if users:
            # Get the public email if available
            user = users[0]
            return getattr(user, 'email', '') or getattr(user, 'public_email', '') or ''
    except gitlab.exceptions.GitlabError as e:
        logger.warning(f"Error fetching user email for {username}: {e}")
    return ''


def is_user_active(gl: gitlab.Gitlab, email: str) -> bool:
    """
    Check if a GitLab user with the given email is active.

    Args:
        gl: Authenticated GitLab client
        email: User's email address

    Returns:
        True if user is active, False otherwise
    """
    try:
        users = gl.users.list(search=email, per_page=1)
        if users:
            user = users[0]
            return user.state == 'active'
    except gitlab.exceptions.GitlabError as e:
        logger.warning(f"Error checking user status for {email}: {e}")
    return False


def get_notification_email(gl: gitlab.Gitlab, committer_email: str, fallback_email: str) -> str:
    """
    Get the email address to use for notifications.
    Uses committer email if user is active, otherwise uses fallback email.

    Args:
        gl: Authenticated GitLab client
        committer_email: Original committer's email
        fallback_email: Fallback email if user is inactive

    Returns:
        Email address to use for notification
    """
    if is_user_active(gl, committer_email):
        return committer_email
    logger.info(f"User {committer_email} is not active, using fallback email")
    return fallback_email


def collect_stale_items_by_email(gl: gitlab.Gitlab, config: dict) -> dict:
    """
    Collect stale branches and merge requests from configured projects and group by email.

    If a stale branch has an open merge request, the MR is used instead of the branch.
    For MRs, the assignee or author email is used for notifications.

    Args:
        gl: Authenticated GitLab client
        config: Configuration dictionary

    Returns:
        Dictionary mapping email addresses to dicts with 'branches' and 'merge_requests' lists
    """
    stale_days = config.get('stale_days', 30)
    fallback_email = config.get('fallback_email', '')
    project_ids = config.get('projects', [])

    email_to_items = {}
    skipped_items = []

    for project_id in project_ids:
        try:
            project = gl.projects.get(project_id)
            branches = get_stale_branches(gl, project_id, stale_days)

            for branch in branches:
                # Check if there's an open MR for this branch
                mr_info = get_merge_request_for_branch(project, branch['branch_name'])

                if mr_info:
                    # Use MR assignee or author email
                    contact_email = mr_info.get('assignee_email') or mr_info.get('author_email', '')

                    # If no email from MR, try to get from username
                    if not contact_email:
                        author_username = mr_info.get('author_username', '')
                        if author_username:
                            contact_email = get_user_email_by_username(gl, author_username)

                    if not contact_email:
                        notification_email = fallback_email
                    else:
                        notification_email = get_notification_email(gl, contact_email, fallback_email)

                    if notification_email:
                        if notification_email not in email_to_items:
                            email_to_items[notification_email] = {'branches': [], 'merge_requests': []}
                        email_to_items[notification_email]['merge_requests'].append(mr_info)
                    else:
                        skipped_items.append({'type': 'merge_request', 'info': mr_info})
                        logger.warning(
                            f"No notification email available for merge request "
                            f"!{mr_info['iid']} in project '{mr_info['project_name']}'. "
                            f"Configure 'fallback_email' to avoid missing notifications."
                        )
                else:
                    # No MR, use branch committer email
                    committer_email = branch.get('committer_email') or branch.get('author_email', '')
                    if not committer_email:
                        notification_email = fallback_email
                    else:
                        notification_email = get_notification_email(gl, committer_email, fallback_email)

                    if notification_email:
                        if notification_email not in email_to_items:
                            email_to_items[notification_email] = {'branches': [], 'merge_requests': []}
                        email_to_items[notification_email]['branches'].append(branch)
                    else:
                        skipped_items.append({'type': 'branch', 'info': branch})
                        logger.warning(
                            f"No notification email available for stale branch "
                            f"'{branch['branch_name']}' in project '{branch['project_name']}'. "
                            f"Original committer: {committer_email or 'unknown'}. "
                            f"Configure 'fallback_email' to avoid missing notifications."
                        )

        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"Failed to get project {project_id}: {e}")

    if skipped_items:
        logger.warning(
            f"Total of {len(skipped_items)} stale item(s) skipped due to "
            f"missing notification email. Configure 'fallback_email' to receive notifications."
        )

    return email_to_items


def collect_stale_branches_by_email(gl: gitlab.Gitlab, config: dict) -> dict:
    """
    Collect all stale branches from configured projects and group by notification email.

    This is a compatibility wrapper around collect_stale_items_by_email that returns
    only branches for backward compatibility.

    Args:
        gl: Authenticated GitLab client
        config: Configuration dictionary

    Returns:
        Dictionary mapping email addresses to lists of stale branches
    """
    items_by_email = collect_stale_items_by_email(gl, config)
    # Convert to old format for backward compatibility
    result = {}
    for email, items in items_by_email.items():
        branches = items.get('branches', [])
        merge_requests = items.get('merge_requests', [])
        # For backward compatibility, combine all items as branches
        all_items = branches + merge_requests
        if all_items:
            result[email] = all_items
    return result


def generate_email_content(
    branches: list,
    stale_days: int,
    cleanup_weeks: int,
    merge_requests: Optional[list] = None
) -> str:
    """
    Generate HTML email content from the template.

    Args:
        branches: List of stale branch information
        stale_days: Number of days for stale threshold
        cleanup_weeks: Number of weeks until automatic cleanup
        merge_requests: Optional list of stale merge request information

    Returns:
        Rendered HTML email content
    """
    template = Template(EMAIL_TEMPLATE)
    return template.render(
        branches=branches,
        merge_requests=merge_requests or [],
        stale_days=stale_days,
        cleanup_weeks=cleanup_weeks
    )


def send_email(
    smtp_config: dict,
    to_email: str,
    subject: str,
    html_content: str,
    dry_run: bool = False
) -> bool:
    """
    Send an email notification.

    Args:
        smtp_config: SMTP server configuration
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content of the email
        dry_run: If True, don't actually send the email

    Returns:
        True if email was sent successfully
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would send email to: {to_email}")
        logger.debug(f"Subject: {subject}")
        return True

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_config['from_email']
    msg['To'] = to_email

    html_part = MIMEText(html_content, 'html')
    msg.attach(html_part)

    try:
        with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
            if smtp_config.get('use_tls', True):
                server.starttls()
            if smtp_config.get('username') and smtp_config.get('password'):
                server.login(smtp_config['username'], smtp_config['password'])
            server.send_message(msg)
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def notify_stale_branches(config: dict, dry_run: bool = False) -> dict:
    """
    Main function to collect stale branches/MRs and send notifications.

    Args:
        config: Configuration dictionary
        dry_run: If True, don't actually send emails

    Returns:
        Summary of notifications sent
    """
    gl = create_gitlab_client(config)
    email_to_items = collect_stale_items_by_email(gl, config)

    stale_days = config.get('stale_days', 30)
    cleanup_weeks = config.get('cleanup_weeks', 4)

    summary = {
        'total_stale_branches': 0,
        'total_stale_merge_requests': 0,
        'emails_sent': 0,
        'emails_failed': 0,
        'recipients': []
    }

    for email, items in email_to_items.items():
        branches = items.get('branches', [])
        merge_requests = items.get('merge_requests', [])

        summary['total_stale_branches'] += len(branches)
        summary['total_stale_merge_requests'] += len(merge_requests)

        total_items = len(branches) + len(merge_requests)
        html_content = generate_email_content(
            branches, stale_days, cleanup_weeks, merge_requests
        )

        # Create descriptive subject
        if merge_requests and branches:
            subject = f"[Action Required] {total_items} Stale Item(s) Require Attention"
        elif merge_requests:
            subject = f"[Action Required] {len(merge_requests)} Stale Merge Request(s) Require Attention"
        else:
            subject = f"[Action Required] {len(branches)} Stale Branch(es) Require Attention"

        success = send_email(
            config['smtp'],
            email,
            subject,
            html_content,
            dry_run=dry_run
        )

        if success:
            summary['emails_sent'] += 1
            summary['recipients'].append(email)
        else:
            summary['emails_failed'] += 1

    return summary


def main() -> Optional[int]:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Notify GitLab users about stale branches and merge requests'
    )
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without sending actual emails'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {args.config}")
        return 1
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in configuration file: {e}")
        return 1
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    summary = notify_stale_branches(config, dry_run=args.dry_run)

    logger.info("=" * 50)
    logger.info("Stale Branch/MR Notification Summary")
    logger.info("=" * 50)
    logger.info(f"Total stale branches found: {summary['total_stale_branches']}")
    logger.info(f"Total stale merge requests found: {summary.get('total_stale_merge_requests', 0)}")
    logger.info(f"Emails sent: {summary['emails_sent']}")
    logger.info(f"Emails failed: {summary['emails_failed']}")
    if summary['recipients']:
        logger.info(f"Recipients: {', '.join(summary['recipients'])}")

    return 0


if __name__ == '__main__':
    exit(main())
