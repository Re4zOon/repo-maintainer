#!/usr/bin/env python3
"""
GitLab Stale Branch/Merge Request Notifier

This script identifies stale branches in GitLab projects and sends
email notifications to their committers about upcoming cleanup.
If a merge request exists for a stale branch, it notifies about the MR instead.
"""

import argparse
import logging
import os
import smtplib
import sqlite3
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
    <meta charset="utf-8">
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

        <p>This is your friendly nudge from the cleanup bot 🤖. The following items in our
        GitLab projects have been snoozing for {{ stale_days }} days and could use a check-in:</p>

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
        cleaned up after {{ cleanup_weeks }} weeks from this notification. The tidy-up bot
        is punctual and does not accept bribes (it runs on cron).</p>

        <p>If you have any questions, please contact the repository maintainers.</p>

        <p>Thanks for keeping things tidy — your future self will thank you.</p>

        <p>Best regards,<br>GitLab Repository Maintenance Team 🧹</p>
    </div>
</body>
</html>
"""

# Default configuration values for notification throttling
DEFAULT_NOTIFICATION_FREQUENCY_DAYS = 7
DEFAULT_DATABASE_PATH = "./notification_history.db"


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required fields."""


def init_database(db_path: str) -> None:
    """
    Initialize the SQLite database for notification tracking.

    Creates the database and tables if they don't exist.

    Args:
        db_path: Path to the SQLite database file
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_email TEXT NOT NULL,
                item_type TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                first_found_at DATETIME NOT NULL,
                last_notified_at DATETIME NOT NULL,
                UNIQUE(recipient_email, item_type, project_id, item_key)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notification_lookup
            ON notification_history(recipient_email, item_type, project_id, item_key)
        ''')

        conn.commit()


def get_last_notification_date(
    db_path: str,
    recipient_email: str,
    item_type: str,
    project_id: int,
    item_key: str
) -> Optional[datetime]:
    """
    Get the last notification date for a specific item.

    Args:
        db_path: Path to the SQLite database file
        recipient_email: Email address of the recipient
        item_type: Type of item ('branch' or 'merge_request')
        project_id: GitLab project ID
        item_key: Unique key for the item (branch name or MR iid)

    Returns:
        datetime of last notification or None if never notified
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            SELECT last_notified_at FROM notification_history
            WHERE recipient_email = ? AND item_type = ? AND project_id = ? AND item_key = ?
        ''', (recipient_email, item_type, project_id, str(item_key)))

        row = cursor.fetchone()

    if row:
        return datetime.fromisoformat(row[0])
    return None


def record_notification(
    db_path: str,
    recipient_email: str,
    item_type: str,
    project_id: int,
    item_key: str,
    notification_time: Optional[datetime] = None
) -> None:
    """
    Record that a notification was sent for a specific item.

    If the item already exists in the database, updates the last_notified_at.
    Otherwise, creates a new record.

    Args:
        db_path: Path to the SQLite database file
        recipient_email: Email address of the recipient
        item_type: Type of item ('branch' or 'merge_request')
        project_id: GitLab project ID
        item_key: Unique key for the item (branch name or MR iid)
        notification_time: Time of notification (defaults to now)
    """
    if notification_time is None:
        notification_time = datetime.now(timezone.utc)

    # Format datetime as ISO string for storage
    time_str = notification_time.isoformat()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO notification_history
                (recipient_email, item_type, project_id, item_key, first_found_at, last_notified_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(recipient_email, item_type, project_id, item_key)
            DO UPDATE SET last_notified_at = excluded.last_notified_at
        ''', (recipient_email, item_type, project_id, str(item_key), time_str, time_str))

        conn.commit()


def has_new_items_for_recipient(
    db_path: str,
    recipient_email: str,
    items: dict
) -> bool:
    """
    Check if there are any new items for a recipient that haven't been notified.

    An item is considered "new" if it doesn't exist in the database or
    was never notified about before.

    Args:
        db_path: Path to the SQLite database file
        recipient_email: Email address of the recipient
        items: Dictionary with 'branches' and 'merge_requests' lists

    Returns:
        True if there are new (never-notified) items, False otherwise
    """
    branches = items.get('branches', [])
    merge_requests = items.get('merge_requests', [])

    for branch in branches:
        project_id = branch.get('project_id')
        branch_name = branch.get('branch_name')
        last_notified = get_last_notification_date(
            db_path, recipient_email, 'branch', project_id, branch_name
        )
        if last_notified is None:
            return True

    for mr in merge_requests:
        project_id = mr.get('project_id')
        mr_iid = mr.get('iid')
        last_notified = get_last_notification_date(
            db_path, recipient_email, 'merge_request', project_id, mr_iid
        )
        if last_notified is None:
            return True

    return False


def should_send_notification(
    db_path: str,
    recipient_email: str,
    items: dict,
    frequency_days: int
) -> bool:
    """
    Determine if a notification should be sent to a recipient.

    A notification is sent if:
    1. There are new items that have never been notified about, OR
    2. The minimum time since the last notification has passed (frequency_days)

    Args:
        db_path: Path to the SQLite database file
        recipient_email: Email address of the recipient
        items: Dictionary with 'branches' and 'merge_requests' lists
        frequency_days: Number of days between notifications

    Returns:
        True if notification should be sent, False otherwise
    """
    branches = items.get('branches', [])
    merge_requests = items.get('merge_requests', [])

    if not branches and not merge_requests:
        return False

    # Check if there are any new (never-notified) items
    if has_new_items_for_recipient(db_path, recipient_email, items):
        return True

    # Check if enough time has passed since the last notification for any item
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=frequency_days)
    oldest_notification = None

    for branch in branches:
        project_id = branch.get('project_id')
        branch_name = branch.get('branch_name')
        last_notified = get_last_notification_date(
            db_path, recipient_email, 'branch', project_id, branch_name
        )
        if last_notified:
            if oldest_notification is None or last_notified < oldest_notification:
                oldest_notification = last_notified

    for mr in merge_requests:
        project_id = mr.get('project_id')
        mr_iid = mr.get('iid')
        last_notified = get_last_notification_date(
            db_path, recipient_email, 'merge_request', project_id, mr_iid
        )
        if last_notified:
            if oldest_notification is None or last_notified < oldest_notification:
                oldest_notification = last_notified

    # If the oldest notification is older than the cutoff, send a new one
    if oldest_notification and oldest_notification < cutoff_date:
        return True

    return False


def record_notifications_for_items(
    db_path: str,
    recipient_email: str,
    items: dict,
    notification_time: Optional[datetime] = None
) -> None:
    """
    Record notifications for all items sent to a recipient.

    Args:
        db_path: Path to the SQLite database file
        recipient_email: Email address of the recipient
        items: Dictionary with 'branches' and 'merge_requests' lists
        notification_time: Time of notification (defaults to now)
    """
    if notification_time is None:
        notification_time = datetime.now(timezone.utc)

    branches = items.get('branches', [])
    merge_requests = items.get('merge_requests', [])

    for branch in branches:
        project_id = branch.get('project_id')
        branch_name = branch.get('branch_name')
        record_notification(
            db_path, recipient_email, 'branch', project_id, branch_name, notification_time
        )

    for mr in merge_requests:
        project_id = mr.get('project_id')
        mr_iid = mr.get('iid')
        record_notification(
            db_path, recipient_email, 'merge_request', project_id, mr_iid, notification_time
        )


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


def get_mr_last_activity_date(project, mr) -> Optional[datetime]:
    """
    Get the last activity date for a merge request, including notes/comments.

    This checks both the MR's updated_at timestamp and the most recent note's
    updated_at to determine the actual last activity on the MR.

    Args:
        project: GitLab project object
        mr: GitLab merge request object

    Returns:
        The most recent activity datetime, or None if cannot be determined
    """
    last_activity = None

    # Get MR updated_at
    try:
        mr_updated = parse_commit_date(mr.updated_at)
        last_activity = mr_updated
    except (ValueError, AttributeError, TypeError):
        pass

    # Check notes (comments) for more recent activity
    try:
        # Get the most recent note by sorting by updated_at descending
        # Note: order_by and sort parameters are well-supported in GitLab API v4+
        notes = project.mergerequests.get(mr.iid).notes.list(
            order_by='updated_at',
            sort='desc',
            per_page=1
        )
        if notes:
            note = notes[0]
            note_date_str = getattr(note, 'updated_at', None)
            if not note_date_str:
                # Fall back to created_at if updated_at is not available
                note_date_str = getattr(note, 'created_at', None)
                if note_date_str:
                    logger.debug(
                        f"Using created_at instead of updated_at for note on MR !{mr.iid}"
                    )
            if note_date_str and isinstance(note_date_str, str):
                try:
                    note_date = parse_commit_date(note_date_str)
                    if last_activity is None or note_date > last_activity:
                        last_activity = note_date
                except (ValueError, TypeError):
                    pass
    except gitlab.exceptions.GitlabError as e:
        logger.debug(f"Error fetching notes for MR !{mr.iid}: {e}")

    return last_activity


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
            return _build_mr_info_dict(project, mr, branch_name)
    except gitlab.exceptions.GitlabError as e:
        logger.warning(f"Error fetching merge requests for branch {branch_name}: {e}")
    return None


def _build_mr_info_dict(project, mr, branch_name: Optional[str] = None) -> dict:
    """
    Build a standardized MR info dictionary from a GitLab MR object.

    Args:
        project: GitLab project object
        mr: GitLab merge request object
        branch_name: Optional source branch name (uses mr.source_branch if not provided)

    Returns:
        Dictionary with MR information
    """
    # Get assignee email if available, otherwise use author
    assignee_email = ''
    assignee_username = ''
    author_email = ''
    author_username = ''

    if hasattr(mr, 'assignee') and mr.assignee:
        assignee_email = _get_email_from_gitlab_object(mr.assignee)
        if isinstance(mr.assignee, dict):
            assignee_username = mr.assignee.get('username', '')
    if hasattr(mr, 'author') and mr.author:
        author_email = _get_email_from_gitlab_object(mr.author)
        if isinstance(mr.author, dict):
            author_username = mr.author.get('username', '')

    # Get the last activity date considering notes/comments
    last_activity_date = get_mr_last_activity_date(project, mr)

    # Format for display
    if last_activity_date:
        last_updated = last_activity_date.strftime('%Y-%m-%d %H:%M:%S')
    else:
        # Fallback to updated_at string if we couldn't parse it
        last_updated = getattr(mr, 'updated_at', 'Unknown')

    # Get author name with consistent isinstance check
    author_name = 'Unknown'
    if hasattr(mr, 'author') and mr.author and isinstance(mr.author, dict):
        author_name = mr.author.get('name', 'Unknown')

    # Use provided branch_name or get from MR
    source_branch = branch_name if branch_name else getattr(mr, 'source_branch', 'Unknown')

    return {
        'iid': mr.iid,
        'title': mr.title,
        'web_url': mr.web_url,
        'branch_name': source_branch,
        'project_id': project.id,
        'project_name': project.name,
        'assignee_email': assignee_email,
        'assignee_username': assignee_username,
        'author_email': author_email,
        'author_name': author_name,
        'author_username': author_username,
        'last_updated': last_updated,
        'updated_at': last_activity_date,
    }


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


def get_stale_merge_requests(gl: gitlab.Gitlab, project_id: int, stale_days: int) -> list:
    """
    Get all open merge requests from a project that have no recent activity.

    Staleness is determined by checking both the MR's updated_at and the most
    recent note/comment activity.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        stale_days: Number of days after which an MR is considered stale

    Returns:
        List of stale MR information dictionaries
    """
    project = gl.projects.get(project_id)
    stale_mrs = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)

    try:
        # Get all open merge requests
        mrs = project.mergerequests.list(state='opened', all=True)

        for mr in mrs:
            mr_info = _build_mr_info_dict(project, mr)
            last_activity = mr_info.get('updated_at')

            # Check if MR is stale (no activity within cutoff period)
            if last_activity and last_activity < cutoff_date:
                stale_mrs.append(mr_info)
            elif last_activity is None:
                # If we couldn't determine activity date, skip this MR to avoid false positives
                logger.debug(
                    f"Could not determine last activity for MR !{mr.iid} "
                    f"in project '{project.name}'. Skipping staleness check."
                )

    except gitlab.exceptions.GitlabError as e:
        logger.error(f"Error fetching merge requests for project {project_id}: {e}")

    return stale_mrs


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


def get_mr_notification_email(gl: gitlab.Gitlab, mr_info: dict, fallback_email: str) -> str:
    """
    Get the email address to use for MR notifications.

    Follows the priority: Assignee → Author → Default (fallback).
    At each step, checks if the user is active before using their email.

    Args:
        gl: Authenticated GitLab client
        mr_info: Dictionary with MR information including assignee/author emails
        fallback_email: Fallback email if no active user is found

    Returns:
        Email address to use for notification
    """
    # Try assignee first
    assignee_email = mr_info.get('assignee_email', '')
    if not assignee_email:
        assignee_username = mr_info.get('assignee_username', '')
        if assignee_username:
            assignee_email = get_user_email_by_username(gl, assignee_username)

    if assignee_email and is_user_active(gl, assignee_email):
        return assignee_email

    if assignee_email:
        logger.info(f"MR assignee {assignee_email} is not active, trying author")

    # Try author next
    author_email = mr_info.get('author_email', '')
    if not author_email:
        author_username = mr_info.get('author_username', '')
        if author_username:
            author_email = get_user_email_by_username(gl, author_username)

    if author_email and is_user_active(gl, author_email):
        return author_email

    if author_email:
        logger.info(f"MR author {author_email} is not active, using fallback email")

    # Fall back to default
    return fallback_email


def collect_stale_items_by_email(gl: gitlab.Gitlab, config: dict) -> dict:
    """
    Collect stale branches and merge requests from configured projects and group by email.

    This function scans for:
    1. Stale MRs - Open MRs with no recent activity (commits, comments, etc.)
    2. Stale branches without MRs - Branches with old commits that don't have an open MR

    Staleness for MRs is determined by the latest activity including notes/comments.
    Notification priority for MRs: Assignee → Author → Default (with active user checks).

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
    # Track which branches have MRs to avoid duplicate notifications
    branches_with_mrs = set()

    for project_id in project_ids:
        try:
            project = gl.projects.get(project_id)

            # First, get all stale MRs directly (this catches MRs even if branch has recent commits)
            stale_mrs = get_stale_merge_requests(gl, project_id, stale_days)

            for mr_info in stale_mrs:
                # Track this branch as having an MR
                branch_key = (project_id, mr_info['branch_name'])
                branches_with_mrs.add(branch_key)

                # Get notification email using MR priority: Assignee → Author → Default
                notification_email = get_mr_notification_email(gl, mr_info, fallback_email)

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

            # Next, get stale branches that don't have MRs
            branches = get_stale_branches(gl, project_id, stale_days)

            for branch in branches:
                branch_key = (project_id, branch['branch_name'])

                # Skip branches that already have an MR (we already handled those above)
                if branch_key in branches_with_mrs:
                    logger.debug(
                        f"Skipping branch '{branch['branch_name']}' - already has stale MR"
                    )
                    continue

                # Check if there's an open MR for this branch (might not be stale MR)
                mr_info = get_merge_request_for_branch(project, branch['branch_name'])

                if mr_info:
                    # Branch has an MR, but MR is not stale (has recent activity)
                    # Skip this branch - the MR takes precedence and is not stale
                    logger.debug(
                        f"Skipping branch '{branch['branch_name']}' - has active MR !{mr_info['iid']}"
                    )
                    continue

                # No MR for this branch - notify about the stale branch
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

    Notifications are throttled based on the notification_frequency_days config.
    A notification is sent if:
    1. There are new items that have never been notified about, OR
    2. The minimum time since the last notification has passed

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
    frequency_days = config.get(
        'notification_frequency_days', DEFAULT_NOTIFICATION_FREQUENCY_DAYS
    )
    db_path = config.get('database_path', DEFAULT_DATABASE_PATH)

    # Initialize the database
    init_database(db_path)

    summary = {
        'total_stale_branches': 0,
        'total_stale_merge_requests': 0,
        'emails_sent': 0,
        'emails_failed': 0,
        'emails_skipped': 0,
        'recipients': []
    }

    for email, items in email_to_items.items():
        branches = items.get('branches', [])
        merge_requests = items.get('merge_requests', [])

        summary['total_stale_branches'] += len(branches)
        summary['total_stale_merge_requests'] += len(merge_requests)

        # Check if we should send notification based on frequency
        if not should_send_notification(db_path, email, items, frequency_days):
            logger.info(
                f"Skipping notification to {email} - "
                f"already notified within {frequency_days} days and no new items"
            )
            summary['emails_skipped'] += 1
            continue

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
            # Record notifications in database (even for dry run to test the flow)
            if not dry_run:
                record_notifications_for_items(db_path, email, items)
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
    logger.info(f"Emails skipped (already notified): {summary.get('emails_skipped', 0)}")
    logger.info(f"Emails failed: {summary['emails_failed']}")
    if summary['recipients']:
        logger.info(f"Recipients: {', '.join(summary['recipients'])}")

    return 0


if __name__ == '__main__':
    exit(main())
