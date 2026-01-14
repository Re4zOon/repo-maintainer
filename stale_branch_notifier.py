#!/usr/bin/env python3
"""
GitLab Stale Branch Notifier

This script identifies stale branches in GitLab projects and sends
email notifications to their committers about upcoming cleanup.
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
    </style>
</head>
<body>
    <div class="header">
        <h1>GitLab Branch Cleanup Notification</h1>
    </div>
    <div class="content">
        <p>Hello,</p>

        <p>The following branches in our GitLab projects have been identified as stale
        (no commits in the last {{ stale_days }} days) and require your attention:</p>

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

        <p><strong>Action Required:</strong> Please review these branches and either:</p>
        <ul>
            <li>Merge them if the work is complete</li>
            <li>Update them with new commits if work is ongoing</li>
            <li>Delete them if they are no longer needed</li>
        </ul>

        <p class="warning">⚠️ Important: Branches that remain inactive will be automatically
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


def collect_stale_branches_by_email(gl: gitlab.Gitlab, config: dict) -> dict:
    """
    Collect all stale branches from configured projects and group by notification email.

    Args:
        gl: Authenticated GitLab client
        config: Configuration dictionary

    Returns:
        Dictionary mapping email addresses to lists of stale branches
    """
    stale_days = config.get('stale_days', 30)
    fallback_email = config.get('fallback_email', '')
    project_ids = config.get('projects', [])

    email_to_branches = {}
    skipped_branches = []

    for project_id in project_ids:
        try:
            branches = get_stale_branches(gl, project_id, stale_days)
            for branch in branches:
                committer_email = branch.get('committer_email') or branch.get('author_email', '')
                if not committer_email:
                    notification_email = fallback_email
                else:
                    notification_email = get_notification_email(gl, committer_email, fallback_email)

                if notification_email:
                    if notification_email not in email_to_branches:
                        email_to_branches[notification_email] = []
                    email_to_branches[notification_email].append(branch)
                else:
                    skipped_branches.append(branch)
                    logger.warning(
                        f"No notification email available for stale branch "
                        f"'{branch['branch_name']}' in project '{branch['project_name']}'. "
                        f"Original committer: {committer_email or 'unknown'}. "
                        f"Configure 'fallback_email' to avoid missing notifications."
                    )

        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"Failed to get project {project_id}: {e}")

    if skipped_branches:
        logger.warning(
            f"Total of {len(skipped_branches)} stale branch(es) skipped due to "
            f"missing notification email. Configure 'fallback_email' to receive notifications."
        )

    return email_to_branches


def generate_email_content(branches: list, stale_days: int, cleanup_weeks: int) -> str:
    """
    Generate HTML email content from the template.

    Args:
        branches: List of stale branch information
        stale_days: Number of days for stale threshold
        cleanup_weeks: Number of weeks until automatic cleanup

    Returns:
        Rendered HTML email content
    """
    template = Template(EMAIL_TEMPLATE)
    return template.render(
        branches=branches,
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
    Main function to collect stale branches and send notifications.

    Args:
        config: Configuration dictionary
        dry_run: If True, don't actually send emails

    Returns:
        Summary of notifications sent
    """
    gl = create_gitlab_client(config)
    email_to_branches = collect_stale_branches_by_email(gl, config)

    stale_days = config.get('stale_days', 30)
    cleanup_weeks = config.get('cleanup_weeks', 4)

    summary = {
        'total_stale_branches': 0,
        'emails_sent': 0,
        'emails_failed': 0,
        'recipients': []
    }

    for email, branches in email_to_branches.items():
        summary['total_stale_branches'] += len(branches)

        html_content = generate_email_content(branches, stale_days, cleanup_weeks)
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
        description='Notify GitLab users about stale branches'
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
    logger.info("Stale Branch Notification Summary")
    logger.info("=" * 50)
    logger.info(f"Total stale branches found: {summary['total_stale_branches']}")
    logger.info(f"Emails sent: {summary['emails_sent']}")
    logger.info(f"Emails failed: {summary['emails_failed']}")
    if summary['recipients']:
        logger.info(f"Recipients: {', '.join(summary['recipients'])}")

    return 0


if __name__ == '__main__':
    exit(main())
