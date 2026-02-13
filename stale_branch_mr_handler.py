#!/usr/bin/env python3
"""
Stale Branch/Merge Request Notifier and Auto-Archiver

This script identifies stale branches in GitLab or GitHub projects and sends
email notifications to their committers about upcoming cleanup.
If a merge request (or pull request on GitHub) exists for a stale branch,
it notifies about that instead.

It can also perform automatic archiving of stale branches/MRs that have exceeded
the cleanup period by:
- Exporting the branch to a local archive folder
- Compressing the export to save space
- Closing any associated merge/pull requests
- Deleting the branch

Supported platforms:
- GitLab (via python-gitlab)
- GitHub (via PyGithub)
"""

import argparse
import functools
import logging
import os
import random
import smtplib
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import gitlab
import yaml
from jinja2 import Template

try:
    from github import Github, GithubException
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False


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
        <h1>Branch Cleanup Notification</h1>
    </div>
    <div class="content">
        <p>Hello,</p>

        <p>{{ greeting }}</p>

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

        <p>Best regards,<br>Repository Maintenance Team 🧹</p>
    </div>
</body>
</html>
"""

# Default configuration values for notification throttling
DEFAULT_NOTIFICATION_FREQUENCY_DAYS = 7
DEFAULT_DATABASE_PATH = "./notification_history.db"

# Default configuration values for automatic archiving
DEFAULT_ARCHIVE_FOLDER = "./archived_branches"
DEFAULT_ENABLE_AUTO_ARCHIVE = False

# Default configuration values for MR comments
DEFAULT_ENABLE_MR_COMMENTS = False
DEFAULT_MR_COMMENT_INACTIVITY_DAYS = 14
DEFAULT_MR_COMMENT_FREQUENCY_DAYS = 7

# Default configuration values for performance
DEFAULT_MAX_WORKERS = 4  # Number of concurrent threads for processing multiple projects

# Default paths for data files (relative to script location)
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_MR_COMMENTS_FILE = os.path.join(DEFAULT_DATA_DIR, "mr_reminder_comments.txt")
DEFAULT_EMAIL_GREETINGS_FILE = os.path.join(DEFAULT_DATA_DIR, "email_greetings.txt")

# Fallback list of reminder comments for stale MRs (used if file cannot be loaded)
FALLBACK_MR_REMINDER_COMMENTS = [
    "👋 Hey there! This MR has been gathering digital dust for a while. "
    "Just a friendly nudge to see if it still needs attention. "
    "The code misses you! 🥺",

    "🦥 *sloth mode detected* This MR has been moving slower than a sloth "
    "on a lazy Sunday. Time to pick up the pace or let it rest in peace? 🪦",

    "🧹 The cleanup bot is back! This MR hasn't had any activity recently. "
    "Don't worry, I'm not here to judge, just to remind. Maybe merge it? Maybe close it? "
    "The suspense is killing me! 😅",

    "🕸️ *blows away cobwebs* Hello? Anyone there? This MR is starting to feel "
    "like an abandoned haunted house. Let's either bring it back to life or give it a proper burial! 👻",

    "⏰ Tick-tock! This MR is aging like fine wine... or maybe like milk? 🥛 "
    "Either way, it could use some love. Your future self will thank you! 🙏",
]

# Fallback list of email greetings (used if file cannot be loaded)
FALLBACK_EMAIL_GREETINGS = [
    (
        "This is your friendly nudge from the cleanup bot 🤖. The following items in our "
        "GitLab projects have been snoozing for {{ stale_days }} days and could use a check-in:"
    ),
    (
        "Beep boop! 🤖 Your friendly neighborhood cleanup bot here! I've noticed some items "
        "that have been enjoying an extended vacation ({{ stale_days }} days to be exact):"
    ),
    (
        "*adjusts monocle* 🧐 Excuse me, but it appears some of your code has been gathering "
        "dust for {{ stale_days }} days. Perhaps it's time for a spring cleaning?"
    ),
    (
        "🎺 Attention! This is not a drill! (Okay, maybe it's a friendly drill.) "
        "Some items have been idle for {{ stale_days }} days:"
    ),
    (
        "👋 Hey there, code wrangler! Your branches and MRs have been grazing peacefully "
        "for {{ stale_days }} days. Time to round them up!"
    ),
]

# Cache for loaded messages - uses functools.lru_cache for thread-safety
# The cache is keyed by file path to support different config files


@functools.lru_cache(maxsize=16)
def _load_messages_cached(file_path: str) -> tuple:
    """
    Load messages from file with caching.

    Uses lru_cache for thread-safe caching keyed by file path.
    Returns a tuple for immutability (required by lru_cache).

    Args:
        file_path: Path to the text file containing messages

    Returns:
        Tuple of messages loaded from the file

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the file contains no valid messages
    """
    messages = load_messages_from_file(file_path)
    return tuple(messages)


def load_messages_from_file(file_path: str) -> List[str]:
    """
    Load messages from a text file.

    Each message is separated by a blank line.
    Lines starting with # are treated as comments and ignored.

    Args:
        file_path: Path to the text file containing messages

    Returns:
        List of messages loaded from the file

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the file contains no valid messages
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Messages file not found: {file_path}")

    messages = []
    current_message_lines = []

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()

            # Skip comment lines
            if stripped.startswith('#'):
                continue

            # Empty line marks end of current message
            if not stripped:
                if current_message_lines:
                    messages.append(' '.join(current_message_lines))
                    current_message_lines = []
            else:
                current_message_lines.append(stripped)

        # Don't forget the last message if file doesn't end with blank line
        if current_message_lines:
            messages.append(' '.join(current_message_lines))

    if not messages:
        raise ValueError(f"No valid messages found in file: {file_path}")

    return messages


def _get_config_file_path(config: Optional[dict], config_key: str, default_path: str) -> str:
    """
    Get file path from config or use default.

    Args:
        config: Optional configuration dictionary
        config_key: Key to look up in config
        default_path: Default path to use if not in config

    Returns:
        File path from config or default
    """
    if config and config.get(config_key):
        return config[config_key]
    return default_path


def get_mr_reminder_comments(config: Optional[dict] = None) -> List[str]:
    """
    Get the list of MR reminder comments.

    Loads from file with thread-safe caching keyed by file path.
    Falls back to hardcoded list if file cannot be loaded.

    Args:
        config: Optional configuration dictionary with 'mr_comments_file' path

    Returns:
        List of MR reminder comments
    """
    file_path = _get_config_file_path(config, 'mr_comments_file', DEFAULT_MR_COMMENTS_FILE)

    try:
        comments = _load_messages_cached(file_path)
        logger.debug(f"Using {len(comments)} MR reminder comments from {file_path}")
        return list(comments)
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"Could not load MR comments from file: {e}. Using fallback comments.")
        return list(FALLBACK_MR_REMINDER_COMMENTS)


def get_email_greetings(config: Optional[dict] = None) -> List[str]:
    """
    Get the list of email greetings.

    Loads from file with thread-safe caching keyed by file path.
    Falls back to hardcoded list if file cannot be loaded.

    Args:
        config: Optional configuration dictionary with 'email_greetings_file' path

    Returns:
        List of email greetings
    """
    file_path = _get_config_file_path(config, 'email_greetings_file', DEFAULT_EMAIL_GREETINGS_FILE)

    try:
        greetings = _load_messages_cached(file_path)
        logger.debug(f"Using {len(greetings)} email greetings from {file_path}")
        return list(greetings)
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"Could not load email greetings from file: {e}. Using fallback greetings.")
        return list(FALLBACK_EMAIL_GREETINGS)


def get_random_mr_comment(config: Optional[dict] = None) -> str:
    """
    Get a random MR reminder comment.

    Args:
        config: Optional configuration dictionary

    Returns:
        A randomly selected MR reminder comment
    """
    comments = get_mr_reminder_comments(config)
    return random.choice(comments)


def get_random_email_greeting(stale_days: int, config: Optional[dict] = None) -> str:
    """
    Get a random email greeting with the stale_days variable rendered.

    Args:
        stale_days: Number of days for stale threshold (used in template rendering)
        config: Optional configuration dictionary

    Returns:
        A randomly selected email greeting with stale_days rendered
    """
    greetings = get_email_greetings(config)
    greeting_template = random.choice(greetings)
    # Render the template with stale_days
    template = Template(greeting_template)
    return template.render(stale_days=stale_days)


# For backwards compatibility, keep MR_REMINDER_COMMENTS as an alias
# This constant now serves only as a static fallback and is not dynamically populated
MR_REMINDER_COMMENTS = FALLBACK_MR_REMINDER_COMMENTS


def get_validated_max_workers(config: dict) -> int:
    """
    Get and validate the max_workers configuration value.

    Ensures max_workers is a positive integer within a reasonable range (1-32).
    Invalid values are logged and replaced with the default.

    Args:
        config: Configuration dictionary

    Returns:
        Validated max_workers value (1-32)
    """
    raw_max_workers = config.get('max_workers', DEFAULT_MAX_WORKERS)
    
    # Try to convert to int
    try:
        max_workers = int(raw_max_workers)
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid 'max_workers' value {raw_max_workers!r} in config; "
            f"falling back to default {DEFAULT_MAX_WORKERS}"
        )
        return DEFAULT_MAX_WORKERS
    
    # Clamp to a reasonable, safe range (1-32)
    if max_workers < 1 or max_workers > 32:
        clamped = min(max(max_workers, 1), 32)
        logger.warning(
            f"Configured 'max_workers' ({max_workers}) is out of allowed range 1-32; "
            f"using {clamped} instead"
        )
        return clamped
    
    return max_workers


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

        # Create table for tracking MR comments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mr_comment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                mr_iid INTEGER NOT NULL,
                comment_index INTEGER NOT NULL,
                last_commented_at DATETIME NOT NULL,
                UNIQUE(project_id, mr_iid)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mr_comment_lookup
            ON mr_comment_history(project_id, mr_iid)
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


# =============================================================================
# MR Comment Functions
# =============================================================================


def get_last_mr_comment_info(
    db_path: str,
    project_id: int,
    mr_iid: int
) -> Optional[tuple]:
    """
    Get the last comment information for a specific MR.

    Args:
        db_path: Path to the SQLite database file
        project_id: GitLab project ID
        mr_iid: Merge request internal ID

    Returns:
        Tuple of (last_commented_at, comment_index) or None if never commented
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            SELECT last_commented_at, comment_index FROM mr_comment_history
            WHERE project_id = ? AND mr_iid = ?
        ''', (project_id, mr_iid))

        row = cursor.fetchone()

    if row:
        return (datetime.fromisoformat(row[0]), row[1])
    return None


def record_mr_comment(
    db_path: str,
    project_id: int,
    mr_iid: int,
    comment_index: int,
    comment_time: Optional[datetime] = None
) -> None:
    """
    Record that a comment was posted to a specific MR.

    Args:
        db_path: Path to the SQLite database file
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
        comment_index: Index of the comment used from MR_REMINDER_COMMENTS
        comment_time: Time of comment (defaults to now)
    """
    if comment_time is None:
        comment_time = datetime.now(timezone.utc)

    time_str = comment_time.isoformat()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO mr_comment_history
                (project_id, mr_iid, comment_index, last_commented_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, mr_iid)
            DO UPDATE SET
                comment_index = excluded.comment_index,
                last_commented_at = excluded.last_commented_at
        ''', (project_id, mr_iid, comment_index, time_str))

        conn.commit()


def should_post_mr_comment(
    db_path: str,
    project_id: int,
    mr_iid: int,
    mr_last_activity: Optional[datetime],
    inactivity_days: int,
    frequency_days: int
) -> bool:
    """
    Determine if a reminder comment should be posted to an MR.

    A comment should be posted if:
    1. The MR has been inactive for at least inactivity_days
    2. No comment has been posted by this bot, OR the last comment was at least
       frequency_days ago

    Args:
        db_path: Path to the SQLite database file
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
        mr_last_activity: Last activity datetime of the MR
        inactivity_days: Days of inactivity before posting first comment
        frequency_days: Days between subsequent comments

    Returns:
        True if a comment should be posted, False otherwise
    """
    if mr_last_activity is None:
        return False

    # Check if MR has been inactive long enough for a comment
    inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=inactivity_days)
    if mr_last_activity > inactivity_cutoff:
        return False

    # Check last comment info
    comment_info = get_last_mr_comment_info(db_path, project_id, mr_iid)

    if comment_info is None:
        # Never commented before, should post
        return True

    last_commented_at, _ = comment_info
    frequency_cutoff = datetime.now(timezone.utc) - timedelta(days=frequency_days)

    # Post if enough time has passed since last comment
    return last_commented_at < frequency_cutoff


def get_next_comment_index(
    db_path: str,
    project_id: int,
    mr_iid: int,
    config: Optional[dict] = None
) -> int:
    """
    Get the next comment index to use for an MR.

    Cycles through the available comments to provide variety.

    Args:
        db_path: Path to the SQLite database file
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
        config: Optional configuration dictionary

    Returns:
        Index of the next comment to use
    """
    comment_info = get_last_mr_comment_info(db_path, project_id, mr_iid)
    comments = get_mr_reminder_comments(config)

    if comment_info is None:
        # For new MRs, use a random index to ensure variety
        return random.randint(0, len(comments) - 1)

    _, last_index = comment_info
    # Cycle to the next comment (wrap around if needed)
    return (last_index + 1) % len(comments)


def post_mr_reminder_comment(
    gl: gitlab.Gitlab,
    project_id: int,
    mr_iid: int,
    comment_text: str,
    dry_run: bool = False
) -> bool:
    """
    Post a reminder comment to a merge request.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
        comment_text: Text of the comment to post
        dry_run: If True, don't actually post the comment

    Returns:
        True if comment was posted successfully, False otherwise
    """
    try:
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)

        if dry_run:
            logger.info(f"[DRY RUN] Would post reminder comment to MR !{mr_iid} in project {project_id}")
            logger.debug(f"Comment text: {comment_text[:100]}...")
            return True

        mr.notes.create({'body': comment_text})
        logger.info(f"Posted reminder comment to MR !{mr_iid} in project {project_id}")
        return True

    except gitlab.exceptions.GitlabError as e:
        logger.error(f"Error posting comment to MR !{mr_iid} in project {project_id}: {e}")
        return False


def _process_project_mr_comments(
    gl: gitlab.Gitlab,
    project_id: int,
    inactivity_days: int,
    frequency_days: int,
    db_path: str,
    comments: list,
    config: dict,
    dry_run: bool = False
) -> dict:
    """
    Process stale MR comments for a single project.

    This is a helper function designed to be run in parallel for multiple projects.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        inactivity_days: Days of inactivity threshold
        frequency_days: Days between comments
        db_path: Path to database
        comments: List of comment texts
        config: Configuration dictionary
        dry_run: If True, don't actually post comments

    Returns:
        Summary dict for this project
    """
    summary = {
        'comments_posted': 0,
        'comments_skipped': 0,
        'comments_failed': 0,
        'commented_mrs': []
    }

    try:
        # Get stale MRs using the inactivity_days threshold
        stale_mrs = get_stale_merge_requests(gl, project_id, inactivity_days)

        for mr_info in stale_mrs:
            mr_iid = mr_info['iid']
            mr_last_activity = mr_info.get('updated_at')

            # Check if we should post a comment
            if not should_post_mr_comment(
                db_path, project_id, mr_iid, mr_last_activity, inactivity_days, frequency_days
            ):
                summary['comments_skipped'] += 1
                logger.debug(
                    f"Skipping comment for MR !{mr_iid} in project {project_id} - "
                    f"already commented recently"
                )
                continue

            # Get the next comment to use
            comment_index = get_next_comment_index(db_path, project_id, mr_iid, config)
            comment_text = comments[comment_index]

            # Post the comment
            if post_mr_reminder_comment(gl, project_id, mr_iid, comment_text, dry_run=dry_run):
                summary['comments_posted'] += 1
                summary['commented_mrs'].append({
                    'project_id': project_id,
                    'project_name': mr_info.get('project_name', 'Unknown'),
                    'mr_iid': mr_iid,
                    'mr_title': mr_info.get('title', 'Unknown'),
                })
                # Record the comment (unless dry run)
                if not dry_run:
                    record_mr_comment(db_path, project_id, mr_iid, comment_index)
            else:
                summary['comments_failed'] += 1

    except gitlab.exceptions.GitlabGetError as e:
        logger.error(f"Failed to get project {project_id}: {e}")

    return summary


def process_stale_mr_comments(
    gl: gitlab.Gitlab,
    config: dict,
    dry_run: bool = False
) -> dict:
    """
    Process stale MRs and post reminder comments where appropriate.

    Uses parallel processing to handle multiple projects concurrently for improved performance.
    This function:
    1. Identifies stale MRs based on inactivity_days config
    2. Checks if a reminder comment should be posted (based on frequency_days)
    3. Posts comments to MRs that need them
    4. Records the comments in the database

    Args:
        gl: Authenticated GitLab client
        config: Configuration dictionary
        dry_run: If True, don't actually post comments

    Returns:
        Summary of comment operations
    """
    inactivity_days = config.get('mr_comment_inactivity_days', DEFAULT_MR_COMMENT_INACTIVITY_DAYS)
    frequency_days = config.get('mr_comment_frequency_days', DEFAULT_MR_COMMENT_FREQUENCY_DAYS)
    db_path = config.get('database_path', DEFAULT_DATABASE_PATH)
    project_ids = config.get('projects', [])
    max_workers = get_validated_max_workers(config)

    # Load comments from file (will be cached after first call)
    comments = get_mr_reminder_comments(config)

    combined_summary = {
        'comments_posted': 0,
        'comments_skipped': 0,
        'comments_failed': 0,
        'commented_mrs': []
    }

    # Process projects in parallel for better performance
    # Note: python-gitlab library is generally thread-safe for read operations.
    # The shared GitLab client (gl) is used across threads for API calls.
    # If you encounter issues with your GitLab version, consider reducing max_workers.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all project processing tasks
        future_to_project = {
            executor.submit(
                _process_project_mr_comments,
                gl, project_id, inactivity_days, frequency_days,
                db_path, comments, config, dry_run
            ): project_id
            for project_id in project_ids
        }

        # Collect results as they complete
        for future in as_completed(future_to_project):
            project_id = future_to_project[future]
            try:
                project_summary = future.result()
                combined_summary['comments_posted'] += project_summary['comments_posted']
                combined_summary['comments_skipped'] += project_summary['comments_skipped']
                combined_summary['comments_failed'] += project_summary['comments_failed']
                combined_summary['commented_mrs'].extend(project_summary['commented_mrs'])
            except Exception as e:
                logger.error(f"Error processing MR comments for project {project_id}: {e}")

    return combined_summary


# =============================================================================
# End of MR Comment Functions
# =============================================================================


def validate_config(config: dict) -> None:
    """
    Validate that all required configuration keys are present.

    Supports both GitLab and GitHub platforms based on the 'platform' key.
    When platform is 'gitlab' (default), requires 'gitlab' section.
    When platform is 'github', requires 'github' section.

    Args:
        config: Configuration dictionary to validate

    Raises:
        ConfigurationError: If required keys are missing
    """
    required_smtp_keys = ['host', 'port', 'from_email']

    if not config:
        raise ConfigurationError("Configuration is empty")

    platform = config.get('platform', 'gitlab')

    if platform not in ('gitlab', 'github'):
        raise ConfigurationError(
            f"Unsupported platform: '{platform}'. Must be 'gitlab' or 'github'."
        )

    if platform == 'github':
        if not HAS_GITHUB:
            raise ConfigurationError(
                "PyGithub is required for GitHub support. "
                "Install it with: pip install PyGithub"
            )
        if 'github' not in config:
            raise ConfigurationError("Missing 'github' section in configuration")
        required_github_keys = ['token']
        for key in required_github_keys:
            if key not in config['github']:
                raise ConfigurationError(f"Missing required GitHub config key: '{key}'")
    else:
        # GitLab
        required_gitlab_keys = ['url', 'private_token']
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


def create_github_client(config: dict):
    """
    Create and authenticate a GitHub client.

    Args:
        config: Configuration dictionary with 'github' section

    Returns:
        Authenticated PyGithub Github client

    Raises:
        ConfigurationError: If PyGithub is not installed
    """
    if not HAS_GITHUB:
        raise ConfigurationError(
            "PyGithub is required for GitHub support. "
            "Install it with: pip install PyGithub"
        )
    token = config['github']['token']
    api_url = config['github'].get('api_url')
    try:
        if api_url:
            gh = Github(login_or_token=token, base_url=api_url)
        else:
            gh = Github(login_or_token=token)
        # Verify authentication by fetching the authenticated user
        gh.get_user().login
    except GithubException as e:
        raise ConfigurationError(
            f"Failed to authenticate with GitHub: {e.data.get('message', str(e)) if hasattr(e, 'data') and e.data else str(e)}"
        ) from e
    return gh


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

    Uses pagination to efficiently handle large repositories with many branches.

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

    # Use pagination for protected branches to reduce memory usage
    protected_branches = {pb.name for pb in project.protectedbranches.list(iterator=True)}

    # Use iterator for memory-efficient iteration over all branches
    for branch in project.branches.list(iterator=True):
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
        notes_iter = project.mergerequests.get(mr.iid).notes.list(
            order_by='updated_at',
            sort='desc',
            per_page=1,
            iterator=True
        )
        note = next(iter(notes_iter), None)
        if note is not None:
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
        mrs_iter = project.mergerequests.list(
            source_branch=branch_name,
            state='opened',
            per_page=1,
            iterator=True
        )
        mr = next(iter(mrs_iter), None)
        if mr is not None:
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
        users_iter = gl.users.list(username=username, per_page=1, iterator=True)
        user = next(iter(users_iter), None)
        if user is not None:
            # Get the public email if available
            return getattr(user, 'email', '') or getattr(user, 'public_email', '') or ''
    except gitlab.exceptions.GitlabError as e:
        logger.warning(f"Error fetching user email for {username}: {e}")
    return ''


def get_stale_merge_requests(gl: gitlab.Gitlab, project_id: int, stale_days: int) -> list:
    """
    Get all open merge requests from a project that have no recent activity.

    Uses pagination to efficiently handle large repositories with many MRs.
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
        # Use iterator for memory-efficient iteration over all open merge requests
        mrs = project.mergerequests.list(state='opened', iterator=True)

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


# =============================================================================
# Automatic Archiving Functions
# =============================================================================


def is_ready_for_archiving(
    item_age: Optional[datetime],
    stale_days: int,
    cleanup_weeks: int
) -> bool:
    """
    Check if a branch/MR is old enough to be archived.

    An item is ready for archiving if:
    1. It has been stale (no activity) for at least stale_days
    2. It has been stale for at least cleanup_weeks beyond the initial stale period

    Args:
        item_age: The last activity datetime of the item
        stale_days: Number of days after which an item is considered stale
        cleanup_weeks: Number of weeks after stale notification before archiving

    Returns:
        True if the item is ready for archiving, False otherwise
    """
    if item_age is None:
        return False

    # Total age required: stale_days + cleanup_weeks
    total_days_required = stale_days + (cleanup_weeks * 7)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=total_days_required)

    return item_age < cutoff_date


def export_branch_to_archive(
    gl: gitlab.Gitlab,
    project_id: int,
    branch_name: str,
    archive_folder: str,
    project_name: str
) -> Optional[str]:
    """
    Export a specific branch to a local archive file using git archive.

    This function exports only the specified branch (not the full repository)
    to a tar.gz compressed archive.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        branch_name: Name of the branch to export
        archive_folder: Local folder to store the archive
        project_name: Name of the project (for archive naming)

    Returns:
        Path to the created archive file, or None if export failed
    """
    try:
        project = gl.projects.get(project_id)

        # Create archive folder if it doesn't exist
        os.makedirs(archive_folder, exist_ok=True)

        # Create a safe filename
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        safe_project_name = "".join(
            c if c.isalnum() or c in '-_' else '_' for c in project_name
        )
        safe_branch_name = "".join(
            c if c.isalnum() or c in '-_' else '_' for c in branch_name
        )
        archive_filename = f"{safe_project_name}_{safe_branch_name}_{timestamp}.tar.gz"
        archive_path = os.path.join(archive_folder, archive_filename)

        # Use GitLab API to download archive of the branch
        logger.info(
            f"Exporting branch '{branch_name}' from project '{project_name}' "
            f"to {archive_path}"
        )

        # Get the archive from GitLab API
        archive_data = project.repository_archive(sha=branch_name, format='tar.gz')

        # Write to file
        with open(archive_path, 'wb') as f:
            f.write(archive_data)

        logger.info(f"Successfully exported branch to {archive_path}")
        return archive_path

    except gitlab.exceptions.GitlabError as e:
        logger.error(f"GitLab error exporting branch '{branch_name}': {e}")
        return None
    except OSError as e:
        logger.error(f"File system error exporting branch '{branch_name}': {e}")
        return None


def close_merge_request(
    gl: gitlab.Gitlab,
    project_id: int,
    mr_iid: int,
    dry_run: bool = False
) -> bool:
    """
    Close a merge request.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
        dry_run: If True, don't actually close the MR

    Returns:
        True if MR was closed successfully, False otherwise
    """
    try:
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)

        if dry_run:
            logger.info(f"[DRY RUN] Would close MR !{mr_iid} in project {project_id}")
            return True

        # Close the MR with a note explaining the automatic archiving
        mr.notes.create({
            'body': (
                "🤖 This merge request has been automatically closed by the "
                "repository maintenance bot due to prolonged inactivity. "
                "The source branch has been archived and will be deleted. "
                "If this work is still needed, please create a new branch "
                "and merge request."
            )
        })
        mr.state_event = 'close'
        mr.save()

        logger.info(f"Successfully closed MR !{mr_iid} in project {project_id}")
        return True

    except gitlab.exceptions.GitlabError as e:
        logger.error(f"Error closing MR !{mr_iid} in project {project_id}: {e}")
        return False


def delete_branch(
    gl: gitlab.Gitlab,
    project_id: int,
    branch_name: str,
    dry_run: bool = False
) -> bool:
    """
    Delete a branch from a GitLab project.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        branch_name: Name of the branch to delete
        dry_run: If True, don't actually delete the branch

    Returns:
        True if branch was deleted successfully, False otherwise
    """
    try:
        project = gl.projects.get(project_id)

        if dry_run:
            logger.info(
                f"[DRY RUN] Would delete branch '{branch_name}' from project {project_id}"
            )
            return True

        project.branches.delete(branch_name)
        logger.info(
            f"Successfully deleted branch '{branch_name}' from project {project_id}"
        )
        return True

    except gitlab.exceptions.GitlabError as e:
        logger.error(
            f"Error deleting branch '{branch_name}' from project {project_id}: {e}"
        )
        return False


def archive_stale_branch(
    gl: gitlab.Gitlab,
    project_id: int,
    project_name: str,
    branch_name: str,
    archive_folder: str,
    dry_run: bool = False
) -> dict:
    """
    Archive a stale branch by exporting it and then deleting it.

    This is a safe operation that:
    1. First exports the branch to a local archive
    2. Only deletes the branch if the export was successful

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        project_name: Name of the project
        branch_name: Name of the branch to archive
        archive_folder: Local folder to store the archive
        dry_run: If True, don't actually archive/delete

    Returns:
        Dictionary with result status and details
    """
    result = {
        'success': False,
        'branch_name': branch_name,
        'project_name': project_name,
        'archived': False,
        'deleted': False,
        'archive_path': None,
        'error': None
    }

    # Step 1: Export the branch to archive
    if dry_run:
        logger.info(
            f"[DRY RUN] Would export branch '{branch_name}' from '{project_name}' "
            f"to {archive_folder}"
        )
        result['archive_path'] = f"{archive_folder}/{project_name}_{branch_name}_<timestamp>.tar.gz"
        result['archived'] = True
    else:
        archive_path = export_branch_to_archive(
            gl, project_id, branch_name, archive_folder, project_name
        )
        if archive_path:
            result['archived'] = True
            result['archive_path'] = archive_path
        else:
            result['error'] = "Failed to export branch - aborting deletion for safety"
            logger.error(
                f"Failed to export branch '{branch_name}' - skipping deletion for safety"
            )
            return result

    # Step 2: Delete the branch (only if export succeeded)
    if delete_branch(gl, project_id, branch_name, dry_run=dry_run):
        result['deleted'] = True
        result['success'] = True
    else:
        result['error'] = "Branch was archived but could not be deleted"

    return result


def archive_stale_mr(
    gl: gitlab.Gitlab,
    project_id: int,
    project_name: str,
    branch_name: str,
    mr_iid: int,
    archive_folder: str,
    dry_run: bool = False
) -> dict:
    """
    Archive a stale merge request and its source branch.

    This is a safe operation that:
    1. First exports the branch to a local archive
    2. Closes the merge request (with a note explaining the closure)
    3. Only deletes the branch if both previous steps succeeded

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        project_name: Name of the project
        branch_name: Name of the source branch
        mr_iid: Merge request internal ID
        archive_folder: Local folder to store the archive
        dry_run: If True, don't actually archive/close/delete

    Returns:
        Dictionary with result status and details
    """
    result = {
        'success': False,
        'branch_name': branch_name,
        'project_name': project_name,
        'mr_iid': mr_iid,
        'archived': False,
        'mr_closed': False,
        'deleted': False,
        'archive_path': None,
        'error': None
    }

    # Step 1: Export the branch to archive
    if dry_run:
        logger.info(
            f"[DRY RUN] Would export branch '{branch_name}' from '{project_name}' "
            f"to {archive_folder}"
        )
        result['archive_path'] = f"{archive_folder}/{project_name}_{branch_name}_<timestamp>.tar.gz"
        result['archived'] = True
    else:
        archive_path = export_branch_to_archive(
            gl, project_id, branch_name, archive_folder, project_name
        )
        if archive_path:
            result['archived'] = True
            result['archive_path'] = archive_path
        else:
            result['error'] = "Failed to export branch - aborting MR close and deletion for safety"
            logger.error(
                f"Failed to export branch '{branch_name}' for MR !{mr_iid} - "
                f"skipping closure and deletion for safety"
            )
            return result

    # Step 2: Close the merge request (only if export succeeded)
    if close_merge_request(gl, project_id, mr_iid, dry_run=dry_run):
        result['mr_closed'] = True
    else:
        result['error'] = "Branch was archived but MR could not be closed"
        # Continue to try to delete the branch anyway since we have the archive

    # Step 3: Delete the branch (only if export succeeded)
    if delete_branch(gl, project_id, branch_name, dry_run=dry_run):
        result['deleted'] = True
        if result['mr_closed']:
            result['success'] = True
    else:
        if result['error']:
            result['error'] += "; Branch could not be deleted"
        else:
            result['error'] = "Branch was archived and MR closed but branch could not be deleted"

    return result


def _process_project_for_archiving(
    gl: gitlab.Gitlab,
    project_id: int,
    stale_days: int,
    cleanup_weeks: int
) -> tuple:
    """
    Process a single project to find items ready for archiving.

    This is a helper function designed to be run in parallel for multiple projects.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        stale_days: Number of days for stale threshold
        cleanup_weeks: Number of weeks for cleanup threshold

    Returns:
        Tuple of (branches_to_archive, mrs_to_archive) for this project
    """
    branches_to_archive = []
    mrs_to_archive = []
    branches_with_mrs = set()

    try:
        project = gl.projects.get(project_id)

        # First, get all stale MRs and check if they're ready for archiving
        stale_mrs = get_stale_merge_requests(gl, project_id, stale_days)

        for mr_info in stale_mrs:
            branch_key = (project_id, mr_info['branch_name'])
            branches_with_mrs.add(branch_key)

            last_activity = mr_info.get('updated_at')
            if is_ready_for_archiving(last_activity, stale_days, cleanup_weeks):
                mrs_to_archive.append(mr_info)
                logger.debug(
                    f"MR !{mr_info['iid']} in '{mr_info['project_name']}' "
                    f"is ready for archiving"
                )

        # Next, get stale branches without MRs
        stale_branches = get_stale_branches(gl, project_id, stale_days)

        for branch in stale_branches:
            branch_key = (project_id, branch['branch_name'])

            # Skip branches that have MRs (we already handled those)
            if branch_key in branches_with_mrs:
                continue

            # Check if there's an open MR for this branch (might not be stale)
            mr_info = get_merge_request_for_branch(project, branch['branch_name'])
            if mr_info:
                # Branch has an active MR, skip it
                continue

            # Parse the commit date to check if ready for archiving
            try:
                commit_date = parse_commit_date(
                    branch['last_commit_date'].replace(' ', 'T') + '+00:00'
                )
            except ValueError:
                logger.warning(
                    f"Could not parse date for branch '{branch['branch_name']}', skipping"
                )
                continue

            if is_ready_for_archiving(commit_date, stale_days, cleanup_weeks):
                branches_to_archive.append(branch)
                logger.debug(
                    f"Branch '{branch['branch_name']}' in '{branch['project_name']}' "
                    f"is ready for archiving"
                )

    except gitlab.exceptions.GitlabGetError as e:
        logger.error(f"Failed to get project {project_id}: {e}")

    return branches_to_archive, mrs_to_archive


def get_branches_ready_for_archiving(
    gl: gitlab.Gitlab,
    config: dict
) -> tuple:
    """
    Get branches and MRs that are ready for archiving.

    Uses parallel processing to handle multiple projects concurrently for improved performance.
    An item is ready for archiving if it has been stale for at least
    stale_days + (cleanup_weeks * 7) days.

    Args:
        gl: Authenticated GitLab client
        config: Configuration dictionary

    Returns:
        Tuple of (branches_to_archive, mrs_to_archive) where each is a list of dicts
    """
    stale_days = config.get('stale_days', 30)
    cleanup_weeks = config.get('cleanup_weeks', 4)
    project_ids = config.get('projects', [])
    max_workers = get_validated_max_workers(config)

    all_branches_to_archive = []
    all_mrs_to_archive = []

    # Process projects in parallel for better performance
    # Note: python-gitlab library is generally thread-safe for read operations.
    # The shared GitLab client (gl) is used across threads for API calls.
    # If you encounter issues with your GitLab version, consider reducing max_workers.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all project processing tasks
        future_to_project = {
            executor.submit(
                _process_project_for_archiving,
                gl, project_id, stale_days, cleanup_weeks
            ): project_id
            for project_id in project_ids
        }

        # Collect results as they complete
        for future in as_completed(future_to_project):
            project_id = future_to_project[future]
            try:
                branches, mrs = future.result()
                all_branches_to_archive.extend(branches)
                all_mrs_to_archive.extend(mrs)
            except Exception as e:
                logger.error(f"Error processing project {project_id} for archiving: {e}")

    return all_branches_to_archive, all_mrs_to_archive


def perform_automatic_archiving(config: dict, dry_run: bool = False) -> dict:
    """
    Main function to perform automatic archiving of stale branches and MRs.

    This function:
    1. Identifies branches and MRs that have exceeded the cleanup period
    2. Exports each branch to a local archive
    3. Closes any associated MRs
    4. Deletes the branches

    Args:
        config: Configuration dictionary
        dry_run: If True, don't actually archive/close/delete

    Returns:
        Summary of archiving operations
    """
    gl = create_gitlab_client(config)

    archive_folder = config.get('archive_folder', DEFAULT_ARCHIVE_FOLDER)
    stale_days = config.get('stale_days', 30)
    cleanup_weeks = config.get('cleanup_weeks', 4)

    summary = {
        'branches_archived': 0,
        'branches_failed': 0,
        'mrs_archived': 0,
        'mrs_failed': 0,
        'archived_items': [],
        'failed_items': [],
        'stale_days': stale_days,
        'cleanup_weeks': cleanup_weeks,
        'total_days': stale_days + (cleanup_weeks * 7),
    }

    branches_to_archive, mrs_to_archive = get_branches_ready_for_archiving(gl, config)

    logger.info(
        f"Found {len(branches_to_archive)} branches and {len(mrs_to_archive)} MRs "
        f"ready for archiving (older than {summary['total_days']} days)"
    )

    # Archive MRs first (includes branch archiving)
    for mr_info in mrs_to_archive:
        result = archive_stale_mr(
            gl=gl,
            project_id=mr_info['project_id'],
            project_name=mr_info['project_name'],
            branch_name=mr_info['branch_name'],
            mr_iid=mr_info['iid'],
            archive_folder=archive_folder,
            dry_run=dry_run
        )

        if result['success']:
            summary['mrs_archived'] += 1
            summary['archived_items'].append({
                'type': 'merge_request',
                'project': mr_info['project_name'],
                'branch': mr_info['branch_name'],
                'mr_iid': mr_info['iid'],
                'archive_path': result['archive_path']
            })
        else:
            summary['mrs_failed'] += 1
            summary['failed_items'].append({
                'type': 'merge_request',
                'project': mr_info['project_name'],
                'branch': mr_info['branch_name'],
                'mr_iid': mr_info['iid'],
                'error': result['error']
            })

    # Archive branches without MRs
    for branch in branches_to_archive:
        result = archive_stale_branch(
            gl=gl,
            project_id=branch['project_id'],
            project_name=branch['project_name'],
            branch_name=branch['branch_name'],
            archive_folder=archive_folder,
            dry_run=dry_run
        )

        if result['success']:
            summary['branches_archived'] += 1
            summary['archived_items'].append({
                'type': 'branch',
                'project': branch['project_name'],
                'branch': branch['branch_name'],
                'archive_path': result['archive_path']
            })
        else:
            summary['branches_failed'] += 1
            summary['failed_items'].append({
                'type': 'branch',
                'project': branch['project_name'],
                'branch': branch['branch_name'],
                'error': result['error']
            })

    return summary


# =============================================================================
# End of Automatic Archiving Functions
# =============================================================================


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
        users_iter = gl.users.list(search=email, per_page=1, iterator=True)
        user = next(iter(users_iter), None)
        if user is not None:
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


def _process_project_stale_items(
    gl: gitlab.Gitlab,
    project_id: int,
    stale_days: int,
    fallback_email: str
) -> tuple:
    """
    Process a single project to collect stale items.

    This is a helper function designed to be run in parallel for multiple projects.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        stale_days: Number of days for stale threshold
        fallback_email: Fallback email for notifications

    Returns:
        Tuple of (email_to_items, skipped_items, branches_with_mrs) for this project
    """
    email_to_items = {}
    skipped_items = []
    branches_with_mrs = set()

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

    return email_to_items, skipped_items, branches_with_mrs


def collect_stale_items_by_email(gl: gitlab.Gitlab, config: dict) -> dict:
    """
    Collect stale branches and merge requests from configured projects and group by email.

    This function scans for:
    1. Stale MRs - Open MRs with no recent activity (commits, comments, etc.)
    2. Stale branches without MRs - Branches with old commits that don't have an open MR

    Uses parallel processing to handle multiple projects concurrently for improved performance.
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
    max_workers = get_validated_max_workers(config)

    email_to_items = {}
    all_skipped_items = []

    # Process projects in parallel for better performance with large numbers of projects
    # Note: python-gitlab library is generally thread-safe for read operations.
    # The shared GitLab client (gl) is used across threads for API calls.
    # If you encounter issues with your GitLab version, consider reducing max_workers.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all project processing tasks
        future_to_project = {
            executor.submit(
                _process_project_stale_items,
                gl, project_id, stale_days, fallback_email
            ): project_id
            for project_id in project_ids
        }

        # Collect results as they complete
        for future in as_completed(future_to_project):
            project_id = future_to_project[future]
            try:
                project_email_items, project_skipped, _ = future.result()

                # Merge results from this project into the overall results
                for email, items in project_email_items.items():
                    if email not in email_to_items:
                        email_to_items[email] = {'branches': [], 'merge_requests': []}
                    email_to_items[email]['branches'].extend(items['branches'])
                    email_to_items[email]['merge_requests'].extend(items['merge_requests'])

                all_skipped_items.extend(project_skipped)

            except Exception as e:
                logger.error(f"Error processing project {project_id}: {e}")

    if all_skipped_items:
        logger.warning(
            f"Total of {len(all_skipped_items)} stale item(s) skipped due to "
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
    merge_requests: Optional[list] = None,
    config: Optional[dict] = None
) -> str:
    """
    Generate HTML email content from the template.

    Args:
        branches: List of stale branch information
        stale_days: Number of days for stale threshold
        cleanup_weeks: Number of weeks until automatic cleanup
        merge_requests: Optional list of stale merge request information
        config: Optional configuration dictionary

    Returns:
        Rendered HTML email content
    """
    # Get a random greeting and render it with stale_days
    greeting = get_random_email_greeting(stale_days, config)

    template = Template(EMAIL_TEMPLATE)
    return template.render(
        branches=branches,
        merge_requests=merge_requests or [],
        stale_days=stale_days,
        cleanup_weeks=cleanup_weeks,
        greeting=greeting
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


# =============================================================================
# GitHub Platform Functions
# =============================================================================


def github_get_stale_branches(gh, repo_name: str, stale_days: int) -> list:
    """
    Get branches from a GitHub repository where the last commit is older than stale_days.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        stale_days: Number of days after which a branch is considered stale

    Returns:
        List of stale branch information dictionaries
    """
    repo = gh.get_repo(repo_name)
    stale_branches = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)

    for branch in repo.get_branches():
        if getattr(branch, 'protected', False):
            logger.debug(f"Skipping protected branch: {branch.name}")
            continue

        commit = branch.commit
        try:
            commit_date = commit.commit.committer.date
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)
        except (AttributeError, TypeError) as e:
            logger.warning(
                f"Could not get commit date for branch {branch.name}: {e}. Skipping."
            )
            continue

        if commit_date < cutoff_date:
            author_name = 'Unknown'
            author_email = ''
            committer_email = ''
            try:
                author_name = commit.commit.author.name or 'Unknown'
                author_email = commit.commit.author.email or ''
                committer_email = commit.commit.committer.email or ''
            except AttributeError as e:
                # Some commits may lack complete author/committer information; use defaults.
                logger.debug(
                    f"Could not get full author/committer info for branch {branch.name}: {e}"
                )

            stale_branches.append({
                'project_id': repo_name,
                'project_name': repo.name,
                'branch_name': branch.name,
                'last_commit_date': commit_date.strftime('%Y-%m-%d %H:%M:%S'),
                'author_name': author_name,
                'author_email': author_email,
                'committer_email': committer_email,
            })

    return stale_branches


def github_get_pr_last_activity_date(pr) -> Optional[datetime]:
    """
    Get the last activity date for a GitHub pull request, including comments.

    Args:
        pr: GitHub PullRequest object

    Returns:
        The most recent activity datetime, or None if cannot be determined
    """
    last_activity = None

    try:
        updated_at = pr.updated_at
        if updated_at:
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            last_activity = updated_at
    except (AttributeError, TypeError) as e:
        # Treat missing or invalid 'updated_at' as unknown activity, but log for diagnostics
        logger.debug(f"Could not determine 'updated_at' for PR #{getattr(pr, 'number', 'unknown')}: {e}")

    # Check comments for more recent activity
    try:
        # Fetch only the most recently updated comment to avoid iterating
        # through the entire paginated list.
        comments = pr.get_issue_comments(sort="updated", direction="desc")
        last_comment = next(iter(comments), None)
        if last_comment:
            comment_date = last_comment.updated_at or last_comment.created_at
            if comment_date:
                if comment_date.tzinfo is None:
                    comment_date = comment_date.replace(tzinfo=timezone.utc)
                if last_activity is None or comment_date > last_activity:
                    last_activity = comment_date
    except GithubException as e:
        logger.debug(f"Error fetching comments for PR #{pr.number}: {e}")

    return last_activity


def _build_github_pr_info_dict(repo, pr, branch_name: Optional[str] = None) -> dict:
    """
    Build a standardized PR info dictionary from a GitHub PR object.

    Uses the same keys as GitLab MR info dicts for compatibility.

    Args:
        repo: GitHub Repository object
        pr: GitHub PullRequest object
        branch_name: Optional source branch name

    Returns:
        Dictionary with PR information (compatible with MR info format)
    """
    assignee_email = ''
    assignee_username = ''
    author_email = ''
    author_username = ''
    author_name = 'Unknown'

    if pr.assignee:
        assignee_username = pr.assignee.login or ''
        assignee_email = pr.assignee.email or ''
    if pr.user:
        author_username = pr.user.login or ''
        author_email = pr.user.email or ''
        author_name = pr.user.name or pr.user.login or 'Unknown'

    last_activity_date = github_get_pr_last_activity_date(pr)

    if last_activity_date:
        last_updated = last_activity_date.strftime('%Y-%m-%d %H:%M:%S')
    else:
        last_updated = str(getattr(pr, 'updated_at', 'Unknown'))

    source_branch = branch_name if branch_name else (pr.head.ref if pr.head else 'Unknown')

    return {
        'iid': pr.number,
        'title': pr.title,
        'web_url': pr.html_url,
        'branch_name': source_branch,
        'project_id': repo.full_name,
        'project_name': repo.name,
        'assignee_email': assignee_email,
        'assignee_username': assignee_username,
        'author_email': author_email,
        'author_name': author_name,
        'author_username': author_username,
        'last_updated': last_updated,
        'updated_at': last_activity_date,
    }


def github_get_merge_request_for_branch(repo, branch_name: str) -> Optional[dict]:
    """
    Get an open pull request for the given branch on GitHub, if one exists.

    Args:
        repo: GitHub Repository object
        branch_name: Name of the head branch

    Returns:
        Dictionary with PR information if found, None otherwise
    """
    try:
        pulls = repo.get_pulls(state='open', head=f"{repo.owner.login}:{branch_name}")
        for pr in pulls:
            return _build_github_pr_info_dict(repo, pr, branch_name)
    except GithubException as e:
        logger.warning(f"Error fetching pull requests for branch {branch_name}: {e}")
    return None


def github_get_stale_pull_requests(gh, repo_name: str, stale_days: int) -> list:
    """
    Get all open pull requests from a GitHub repo that have no recent activity.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        stale_days: Number of days after which a PR is considered stale

    Returns:
        List of stale PR information dictionaries (compatible with MR info format)
    """
    repo = gh.get_repo(repo_name)
    stale_prs = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)

    try:
        pulls = repo.get_pulls(state='open')
        for pr in pulls:
            pr_info = _build_github_pr_info_dict(repo, pr)
            last_activity = pr_info.get('updated_at')

            if last_activity and last_activity < cutoff_date:
                stale_prs.append(pr_info)
            elif last_activity is None:
                logger.debug(
                    f"Could not determine last activity for PR #{pr.number} "
                    f"in repo '{repo.name}'. Skipping staleness check."
                )

    except GithubException as e:
        logger.error(f"Error fetching pull requests for repo {repo_name}: {e}")

    return stale_prs


def github_is_user_active(gh, email: str) -> bool:
    """
    Check if a GitHub user with the given email is active.

    On GitHub, if a user can be found by email search, they are considered active
    (GitHub does not expose a 'blocked' state like GitLab).

    Args:
        gh: Authenticated GitHub client
        email: User's email address

    Returns:
        True if user is found, False otherwise
    """
    try:
        users = gh.search_users(f"{email} in:email")
        for user in users:
            return True
    except GithubException as e:
        logger.warning(f"Error checking user status for {email}: {e}")
    return False


def github_get_user_email_by_username(gh, username: str) -> str:
    """
    Get a user's email by their GitHub username.

    Args:
        gh: Authenticated GitHub client
        username: GitHub username

    Returns:
        User's email address or empty string if not found
    """
    try:
        user = gh.get_user(username)
        return user.email or ''
    except GithubException as e:
        logger.warning(f"Error fetching user email for {username}: {e}")
    return ''


def github_export_branch_to_archive(
    gh,
    repo_name: str,
    branch_name: str,
    archive_folder: str,
    project_name: str
) -> Optional[str]:
    """
    Export a specific branch from a GitHub repo to a local archive file.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        branch_name: Name of the branch to export
        archive_folder: Local folder to store the archive
        project_name: Name of the project (for archive naming)

    Returns:
        Path to the created archive file, or None if export failed
    """
    try:
        repo = gh.get_repo(repo_name)

        os.makedirs(archive_folder, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        safe_project_name = "".join(
            c if c.isalnum() or c in '-_' else '_' for c in project_name
        )
        safe_branch_name = "".join(
            c if c.isalnum() or c in '-_' else '_' for c in branch_name
        )
        archive_filename = f"{safe_project_name}_{safe_branch_name}_{timestamp}.tar.gz"
        archive_path = os.path.join(archive_folder, archive_filename)

        logger.info(
            f"Exporting branch '{branch_name}' from repo '{repo_name}' "
            f"to {archive_path}"
        )

        # Use the authenticated PyGithub requester to download the archive
        # so that private repos are properly handled
        archive_url = repo.get_archive_link('tarball', ref=branch_name)
        status, headers, data = repo._requester.requestBlob("GET", archive_url)
        with open(archive_path, 'wb') as f:
            f.write(data)

        logger.info(f"Successfully exported branch to {archive_path}")
        return archive_path

    except GithubException as e:
        logger.error(f"GitHub error exporting branch '{branch_name}': {e}")
        return None
    except OSError as e:
        logger.error(f"File system error exporting branch '{branch_name}': {e}")
        return None


def github_close_merge_request(
    gh,
    repo_name: str,
    pr_number: int,
    dry_run: bool = False
) -> bool:
    """
    Close a pull request on GitHub.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        pr_number: Pull request number
        dry_run: If True, don't actually close the PR

    Returns:
        True if PR was closed successfully, False otherwise
    """
    try:
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        if dry_run:
            logger.info(f"[DRY RUN] Would close PR #{pr_number} in repo {repo_name}")
            return True

        pr.create_issue_comment(
            "🤖 This pull request has been automatically closed by the "
            "repository maintenance bot due to prolonged inactivity. "
            "The source branch has been archived and will be deleted. "
            "If this work is still needed, please create a new branch "
            "and pull request."
        )
        pr.edit(state='closed')

        logger.info(f"Successfully closed PR #{pr_number} in repo {repo_name}")
        return True

    except GithubException as e:
        logger.error(f"Error closing PR #{pr_number} in repo {repo_name}: {e}")
        return False


def github_delete_branch(
    gh,
    repo_name: str,
    branch_name: str,
    dry_run: bool = False
) -> bool:
    """
    Delete a branch from a GitHub repository.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        branch_name: Name of the branch to delete
        dry_run: If True, don't actually delete the branch

    Returns:
        True if branch was deleted successfully, False otherwise
    """
    try:
        repo = gh.get_repo(repo_name)

        if dry_run:
            logger.info(
                f"[DRY RUN] Would delete branch '{branch_name}' from repo {repo_name}"
            )
            return True

        ref = repo.get_git_ref(f"heads/{branch_name}")
        ref.delete()
        logger.info(
            f"Successfully deleted branch '{branch_name}' from repo {repo_name}"
        )
        return True

    except GithubException as e:
        logger.error(
            f"Error deleting branch '{branch_name}' from repo {repo_name}: {e}"
        )
        return False


def github_post_mr_reminder_comment(
    gh,
    repo_name: str,
    pr_number: int,
    comment_text: str,
    dry_run: bool = False
) -> bool:
    """
    Post a reminder comment to a GitHub pull request.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        pr_number: Pull request number
        comment_text: Text of the comment to post
        dry_run: If True, don't actually post the comment

    Returns:
        True if comment was posted successfully, False otherwise
    """
    try:
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        if dry_run:
            logger.info(f"[DRY RUN] Would post reminder comment to PR #{pr_number} in repo {repo_name}")
            logger.debug(f"Comment text: {comment_text[:100]}...")
            return True

        pr.create_issue_comment(comment_text)
        logger.info(f"Posted reminder comment to PR #{pr_number} in repo {repo_name}")
        return True

    except GithubException as e:
        logger.error(f"Error posting comment to PR #{pr_number} in repo {repo_name}: {e}")
        return False


# =============================================================================
# GitHub-aware Collection/Processing Functions
# =============================================================================


def github_get_notification_email(gh, committer_email: str, fallback_email: str) -> str:
    """
    Get the email address to use for notifications on GitHub.

    Args:
        gh: Authenticated GitHub client
        committer_email: Original committer's email
        fallback_email: Fallback email if user is inactive

    Returns:
        Email address to use for notification
    """
    if github_is_user_active(gh, committer_email):
        return committer_email
    logger.info(f"User {committer_email} is not active, using fallback email")
    return fallback_email


def github_get_mr_notification_email(gh, mr_info: dict, fallback_email: str) -> str:
    """
    Get the email address to use for PR notifications on GitHub.

    Follows the priority: Assignee → Author → Default (fallback).

    Args:
        gh: Authenticated GitHub client
        mr_info: Dictionary with PR information
        fallback_email: Fallback email if no active user is found

    Returns:
        Email address to use for notification
    """
    assignee_email = mr_info.get('assignee_email', '')
    if not assignee_email:
        assignee_username = mr_info.get('assignee_username', '')
        if assignee_username:
            assignee_email = github_get_user_email_by_username(gh, assignee_username)

    if assignee_email and github_is_user_active(gh, assignee_email):
        return assignee_email

    if assignee_email:
        logger.info(f"PR assignee {assignee_email} is not active, trying author")

    author_email = mr_info.get('author_email', '')
    if not author_email:
        author_username = mr_info.get('author_username', '')
        if author_username:
            author_email = github_get_user_email_by_username(gh, author_username)

    if author_email and github_is_user_active(gh, author_email):
        return author_email

    if author_email:
        logger.info(f"PR author {author_email} is not active, using fallback email")

    return fallback_email


def _github_process_project_stale_items(
    gh,
    repo_name: str,
    stale_days: int,
    fallback_email: str
) -> tuple:
    """
    Process a single GitHub repo to collect stale items.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        stale_days: Number of days for stale threshold
        fallback_email: Fallback email for notifications

    Returns:
        Tuple of (email_to_items, skipped_items, branches_with_prs)
    """
    email_to_items = {}
    skipped_items = []
    branches_with_prs = set()

    try:
        repo = gh.get_repo(repo_name)

        # First, get all stale PRs directly
        stale_prs = github_get_stale_pull_requests(gh, repo_name, stale_days)

        for pr_info in stale_prs:
            branch_key = (repo_name, pr_info['branch_name'])
            branches_with_prs.add(branch_key)

            notification_email = github_get_mr_notification_email(gh, pr_info, fallback_email)

            if notification_email:
                if notification_email not in email_to_items:
                    email_to_items[notification_email] = {'branches': [], 'merge_requests': []}
                email_to_items[notification_email]['merge_requests'].append(pr_info)
            else:
                skipped_items.append({'type': 'pull_request', 'info': pr_info})
                logger.warning(
                    f"No notification email available for pull request "
                    f"#{pr_info['iid']} in repo '{pr_info['project_name']}'. "
                    f"Configure 'fallback_email' to avoid missing notifications."
                )

        # Next, get stale branches that don't have PRs
        branches = github_get_stale_branches(gh, repo_name, stale_days)

        for branch in branches:
            branch_key = (repo_name, branch['branch_name'])

            if branch_key in branches_with_prs:
                logger.debug(
                    f"Skipping branch '{branch['branch_name']}' - already has stale PR"
                )
                continue

            pr_info = github_get_merge_request_for_branch(repo, branch['branch_name'])
            if pr_info:
                logger.debug(
                    f"Skipping branch '{branch['branch_name']}' - has active PR #{pr_info['iid']}"
                )
                continue

            committer_email = branch.get('committer_email') or branch.get('author_email', '')
            if not committer_email:
                notification_email = fallback_email
            else:
                notification_email = github_get_notification_email(gh, committer_email, fallback_email)

            if notification_email:
                if notification_email not in email_to_items:
                    email_to_items[notification_email] = {'branches': [], 'merge_requests': []}
                email_to_items[notification_email]['branches'].append(branch)
            else:
                skipped_items.append({'type': 'branch', 'info': branch})
                logger.warning(
                    f"No notification email available for stale branch "
                    f"'{branch['branch_name']}' in repo '{branch['project_name']}'. "
                    f"Original committer: {committer_email or 'unknown'}. "
                    f"Configure 'fallback_email' to avoid missing notifications."
                )

    except GithubException as e:
        logger.error(f"Failed to get repo {repo_name}: {e}")

    return email_to_items, skipped_items, branches_with_prs


def github_collect_stale_items_by_email(gh, config: dict) -> dict:
    """
    Collect stale branches and PRs from configured GitHub repos and group by email.

    Args:
        gh: Authenticated GitHub client
        config: Configuration dictionary

    Returns:
        Dictionary mapping email addresses to dicts with 'branches' and 'merge_requests' lists
    """
    stale_days = config.get('stale_days', 30)
    fallback_email = config.get('fallback_email', '')
    repo_names = config.get('projects', [])
    max_workers = get_validated_max_workers(config)

    email_to_items = {}
    all_skipped_items = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {
            executor.submit(
                _github_process_project_stale_items,
                gh, repo_name, stale_days, fallback_email
            ): repo_name
            for repo_name in repo_names
        }

        for future in as_completed(future_to_repo):
            repo_name = future_to_repo[future]
            try:
                repo_email_items, repo_skipped, _ = future.result()

                for email, items in repo_email_items.items():
                    if email not in email_to_items:
                        email_to_items[email] = {'branches': [], 'merge_requests': []}
                    email_to_items[email]['branches'].extend(items['branches'])
                    email_to_items[email]['merge_requests'].extend(items['merge_requests'])

                all_skipped_items.extend(repo_skipped)

            except Exception as e:
                logger.error(f"Error processing repo {repo_name}: {e}")

    if all_skipped_items:
        logger.warning(
            f"Total of {len(all_skipped_items)} stale item(s) skipped due to "
            f"missing notification email. Configure 'fallback_email' to receive notifications."
        )

    return email_to_items


def _github_process_project_mr_comments(
    gh,
    repo_name: str,
    inactivity_days: int,
    frequency_days: int,
    db_path: str,
    comments: list,
    config: dict,
    dry_run: bool = False
) -> dict:
    """
    Process stale PR comments for a single GitHub repo.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        inactivity_days: Days of inactivity threshold
        frequency_days: Days between comments
        db_path: Path to database
        comments: List of comment texts
        config: Configuration dictionary
        dry_run: If True, don't actually post comments

    Returns:
        Summary dict for this repo
    """
    summary = {
        'comments_posted': 0,
        'comments_skipped': 0,
        'comments_failed': 0,
        'commented_mrs': []
    }

    try:
        stale_prs = github_get_stale_pull_requests(gh, repo_name, inactivity_days)

        for pr_info in stale_prs:
            pr_number = pr_info['iid']
            pr_last_activity = pr_info.get('updated_at')

            if not should_post_mr_comment(
                db_path, repo_name, pr_number, pr_last_activity, inactivity_days, frequency_days
            ):
                summary['comments_skipped'] += 1
                logger.debug(
                    f"Skipping comment for PR #{pr_number} in repo {repo_name} - "
                    f"already commented recently"
                )
                continue

            comment_index = get_next_comment_index(db_path, repo_name, pr_number, config)
            comment_text = comments[comment_index]

            if github_post_mr_reminder_comment(gh, repo_name, pr_number, comment_text, dry_run=dry_run):
                summary['comments_posted'] += 1
                summary['commented_mrs'].append({
                    'project_id': repo_name,
                    'project_name': pr_info.get('project_name', 'Unknown'),
                    'mr_iid': pr_number,
                    'mr_title': pr_info.get('title', 'Unknown'),
                })
                if not dry_run:
                    record_mr_comment(db_path, repo_name, pr_number, comment_index)
            else:
                summary['comments_failed'] += 1

    except GithubException as e:
        logger.error(f"Failed to get repo {repo_name}: {e}")

    return summary


def github_process_stale_mr_comments(
    gh,
    config: dict,
    dry_run: bool = False
) -> dict:
    """
    Process stale PRs on GitHub and post reminder comments where appropriate.

    Args:
        gh: Authenticated GitHub client
        config: Configuration dictionary
        dry_run: If True, don't actually post comments

    Returns:
        Summary of comment operations
    """
    inactivity_days = config.get('mr_comment_inactivity_days', DEFAULT_MR_COMMENT_INACTIVITY_DAYS)
    frequency_days = config.get('mr_comment_frequency_days', DEFAULT_MR_COMMENT_FREQUENCY_DAYS)
    db_path = config.get('database_path', DEFAULT_DATABASE_PATH)
    repo_names = config.get('projects', [])
    max_workers = get_validated_max_workers(config)

    comments = get_mr_reminder_comments(config)

    combined_summary = {
        'comments_posted': 0,
        'comments_skipped': 0,
        'comments_failed': 0,
        'commented_mrs': []
    }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {
            executor.submit(
                _github_process_project_mr_comments,
                gh, repo_name, inactivity_days, frequency_days,
                db_path, comments, config, dry_run
            ): repo_name
            for repo_name in repo_names
        }

        for future in as_completed(future_to_repo):
            repo_name = future_to_repo[future]
            try:
                repo_summary = future.result()
                combined_summary['comments_posted'] += repo_summary['comments_posted']
                combined_summary['comments_skipped'] += repo_summary['comments_skipped']
                combined_summary['comments_failed'] += repo_summary['comments_failed']
                combined_summary['commented_mrs'].extend(repo_summary['commented_mrs'])
            except Exception as e:
                logger.error(f"Error processing PR comments for repo {repo_name}: {e}")

    return combined_summary


def _github_process_project_for_archiving(
    gh,
    repo_name: str,
    stale_days: int,
    cleanup_weeks: int
) -> tuple:
    """
    Process a single GitHub repo to find items ready for archiving.

    Args:
        gh: Authenticated GitHub client
        repo_name: Repository name in "owner/repo" format
        stale_days: Number of days for stale threshold
        cleanup_weeks: Number of weeks for cleanup threshold

    Returns:
        Tuple of (branches_to_archive, prs_to_archive)
    """
    branches_to_archive = []
    prs_to_archive = []
    branches_with_prs = set()

    try:
        repo = gh.get_repo(repo_name)

        stale_prs = github_get_stale_pull_requests(gh, repo_name, stale_days)

        for pr_info in stale_prs:
            branch_key = (repo_name, pr_info['branch_name'])
            branches_with_prs.add(branch_key)

            last_activity = pr_info.get('updated_at')
            if is_ready_for_archiving(last_activity, stale_days, cleanup_weeks):
                prs_to_archive.append(pr_info)
                logger.debug(
                    f"PR #{pr_info['iid']} in '{pr_info['project_name']}' "
                    f"is ready for archiving"
                )

        stale_branches = github_get_stale_branches(gh, repo_name, stale_days)

        for branch in stale_branches:
            branch_key = (repo_name, branch['branch_name'])

            if branch_key in branches_with_prs:
                continue

            pr_info = github_get_merge_request_for_branch(repo, branch['branch_name'])
            if pr_info:
                continue

            try:
                commit_date = parse_commit_date(
                    branch['last_commit_date'].replace(' ', 'T') + '+00:00'
                )
            except ValueError:
                logger.warning(
                    f"Could not parse date for branch '{branch['branch_name']}', skipping"
                )
                continue

            if is_ready_for_archiving(commit_date, stale_days, cleanup_weeks):
                branches_to_archive.append(branch)
                logger.debug(
                    f"Branch '{branch['branch_name']}' in '{branch['project_name']}' "
                    f"is ready for archiving"
                )

    except GithubException as e:
        logger.error(f"Failed to get repo {repo_name}: {e}")

    return branches_to_archive, prs_to_archive


def github_perform_automatic_archiving(config: dict, dry_run: bool = False) -> dict:
    """
    Perform automatic archiving of stale branches and PRs on GitHub.

    Args:
        config: Configuration dictionary
        dry_run: If True, don't actually archive/close/delete

    Returns:
        Summary of archiving operations
    """
    gh = create_github_client(config)

    archive_folder = config.get('archive_folder', DEFAULT_ARCHIVE_FOLDER)
    stale_days = config.get('stale_days', 30)
    cleanup_weeks = config.get('cleanup_weeks', 4)
    repo_names = config.get('projects', [])
    max_workers = get_validated_max_workers(config)

    summary = {
        'branches_archived': 0,
        'branches_failed': 0,
        'mrs_archived': 0,
        'mrs_failed': 0,
        'archived_items': [],
        'failed_items': [],
        'stale_days': stale_days,
        'cleanup_weeks': cleanup_weeks,
        'total_days': stale_days + (cleanup_weeks * 7),
    }

    all_branches_to_archive = []
    all_prs_to_archive = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {
            executor.submit(
                _github_process_project_for_archiving,
                gh, repo_name, stale_days, cleanup_weeks
            ): repo_name
            for repo_name in repo_names
        }

        for future in as_completed(future_to_repo):
            repo_name = future_to_repo[future]
            try:
                branches, prs = future.result()
                all_branches_to_archive.extend(branches)
                all_prs_to_archive.extend(prs)
            except Exception as e:
                logger.error(f"Error processing repo {repo_name} for archiving: {e}")

    logger.info(
        f"Found {len(all_branches_to_archive)} branches and {len(all_prs_to_archive)} PRs "
        f"ready for archiving (older than {summary['total_days']} days)"
    )

    # Archive PRs first
    for pr_info in all_prs_to_archive:
        repo_name = pr_info['project_id']
        branch_name = pr_info['branch_name']
        pr_number = pr_info['iid']
        project_name = pr_info['project_name']

        # Step 1: Export branch
        archived = False
        archive_path = None
        if dry_run:
            logger.info(
                f"[DRY RUN] Would export branch '{branch_name}' from '{project_name}' "
                f"to {archive_folder}"
            )
            archive_path = f"{archive_folder}/{project_name}_{branch_name}_<timestamp>.tar.gz"
            archived = True
        else:
            archive_path = github_export_branch_to_archive(
                gh, repo_name, branch_name, archive_folder, project_name
            )
            if archive_path:
                archived = True
            else:
                summary['mrs_failed'] += 1
                summary['failed_items'].append({
                    'type': 'merge_request',
                    'project': project_name,
                    'branch': branch_name,
                    'mr_iid': pr_number,
                    'error': "Failed to export branch - aborting"
                })
                continue

        # Step 2: Close PR
        mr_closed = github_close_merge_request(gh, repo_name, pr_number, dry_run=dry_run)

        # Step 3: Delete branch
        deleted = github_delete_branch(gh, repo_name, branch_name, dry_run=dry_run)

        if archived and mr_closed and deleted:
            summary['mrs_archived'] += 1
            summary['archived_items'].append({
                'type': 'merge_request',
                'project': project_name,
                'branch': branch_name,
                'mr_iid': pr_number,
                'archive_path': archive_path
            })
        else:
            summary['mrs_failed'] += 1
            summary['failed_items'].append({
                'type': 'merge_request',
                'project': project_name,
                'branch': branch_name,
                'mr_iid': pr_number,
                'error': "Partial failure during archiving"
            })

    # Archive branches without PRs
    for branch in all_branches_to_archive:
        repo_name = branch['project_id']
        branch_name = branch['branch_name']
        project_name = branch['project_name']

        archived = False
        archive_path = None
        if dry_run:
            logger.info(
                f"[DRY RUN] Would export branch '{branch_name}' from '{project_name}' "
                f"to {archive_folder}"
            )
            archive_path = f"{archive_folder}/{project_name}_{branch_name}_<timestamp>.tar.gz"
            archived = True
        else:
            archive_path = github_export_branch_to_archive(
                gh, repo_name, branch_name, archive_folder, project_name
            )
            if archive_path:
                archived = True
            else:
                summary['branches_failed'] += 1
                summary['failed_items'].append({
                    'type': 'branch',
                    'project': project_name,
                    'branch': branch_name,
                    'error': "Failed to export branch - aborting"
                })
                continue

        deleted = github_delete_branch(gh, repo_name, branch_name, dry_run=dry_run)

        if archived and deleted:
            summary['branches_archived'] += 1
            summary['archived_items'].append({
                'type': 'branch',
                'project': project_name,
                'branch': branch_name,
                'archive_path': archive_path
            })
        else:
            summary['branches_failed'] += 1
            summary['failed_items'].append({
                'type': 'branch',
                'project': project_name,
                'branch': branch_name,
                'error': "Branch was archived but could not be deleted"
            })

    return summary


# =============================================================================
# End of GitHub Platform Functions
# =============================================================================


def notify_stale_branches(config: dict, dry_run: bool = False) -> dict:
    """
    Main function to collect stale branches/MRs and send notifications.

    Supports both GitLab and GitHub platforms based on config.
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
    platform = config.get('platform', 'gitlab')
    if platform == 'github':
        gh = create_github_client(config)
        email_to_items = github_collect_stale_items_by_email(gh, config)
    else:
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
            branches, stale_days, cleanup_weeks, merge_requests, config
        )

        # Create descriptive subject
        if merge_requests and branches:
            subject = f"[Action Required] {total_items} Stale Item(s) Require Attention"
        elif merge_requests:
            subject = f"[Action Required] {len(merge_requests)} Stale Merge/Pull Request(s) Require Attention"
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
            # Record notifications in database (only when actually sending)
            if not dry_run:
                record_notifications_for_items(db_path, email, items)
        else:
            summary['emails_failed'] += 1

    return summary


def main() -> Optional[int]:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Notify users about stale branches and merge/pull requests, '
                    'and optionally perform automatic archiving of very old items. '
                    'Supports both GitLab and GitHub platforms.'
    )
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without sending actual emails or performing archiving'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--archive',
        action='store_true',
        help='Enable automatic archiving of stale branches and merge/pull requests that have exceeded '
             'the cleanup period (stale_days + cleanup_weeks). This will: '
             '1) Export branches to archive folder, '
             '2) Close associated merge/pull requests, '
             '3) Delete the branches.'
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

    # Run notification first
    summary = notify_stale_branches(config, dry_run=args.dry_run)

    platform = config.get('platform', 'gitlab')
    mr_label = "pull requests" if platform == "github" else "merge requests"

    logger.info("=" * 50)
    logger.info("Stale Branch/MR/PR Notification Summary")
    logger.info("=" * 50)
    logger.info(f"Total stale branches found: {summary['total_stale_branches']}")
    logger.info(f"Total stale {mr_label} found: {summary.get('total_stale_merge_requests', 0)}")
    logger.info(f"Emails sent: {summary['emails_sent']}")
    logger.info(f"Emails skipped (already notified): {summary.get('emails_skipped', 0)}")
    logger.info(f"Emails failed: {summary['emails_failed']}")
    if summary['recipients']:
        logger.info(f"Recipients: {', '.join(summary['recipients'])}")

    # Run MR/PR commenting if enabled
    if config.get('enable_mr_comments', DEFAULT_ENABLE_MR_COMMENTS):
        logger.info("")
        logger.info("=" * 50)
        logger.info("MR/PR Reminder Comments")
        logger.info("=" * 50)

        platform = config.get('platform', 'gitlab')
        if platform == 'github':
            gh = create_github_client(config)
            comment_summary = github_process_stale_mr_comments(gh, config, dry_run=args.dry_run)
        else:
            # Create GitLab client for comment posting
            gl = create_gitlab_client(config)
            comment_summary = process_stale_mr_comments(gl, config, dry_run=args.dry_run)

        inactivity_days = config.get('mr_comment_inactivity_days', DEFAULT_MR_COMMENT_INACTIVITY_DAYS)
        frequency_days = config.get('mr_comment_frequency_days', DEFAULT_MR_COMMENT_FREQUENCY_DAYS)

        logger.info(f"Inactivity threshold: {inactivity_days} days")
        logger.info(f"Comment frequency: every {frequency_days} days")
        logger.info(f"Comments posted: {comment_summary['comments_posted']}")
        logger.info(f"Comments skipped (already commented recently): {comment_summary['comments_skipped']}")
        logger.info(f"Comments failed: {comment_summary['comments_failed']}")

        if comment_summary['commented_mrs']:
            if platform == 'github':
                logger.info("PRs commented:")
                for mr in comment_summary['commented_mrs']:
                    logger.info(f"  - #{mr['mr_iid']} in {mr['project_name']}: {mr['mr_title']}")
            else:
                logger.info("MRs commented:")
                for mr in comment_summary['commented_mrs']:
                    logger.info(f"  - !{mr['mr_iid']} in {mr['project_name']}: {mr['mr_title']}")

    # Run automatic archiving if enabled
    if args.archive or config.get('enable_auto_archive', DEFAULT_ENABLE_AUTO_ARCHIVE):
        logger.info("")
        logger.info("=" * 50)
        logger.info("Automatic Archiving")
        logger.info("=" * 50)

        if config.get('platform', 'gitlab') == 'github':
            archive_summary = github_perform_automatic_archiving(config, dry_run=args.dry_run)
        else:
            archive_summary = perform_automatic_archiving(config, dry_run=args.dry_run)

        logger.info(f"Items older than: {archive_summary['total_days']} days "
                    f"({archive_summary['stale_days']} stale + "
                    f"{archive_summary['cleanup_weeks']} weeks cleanup)")
        logger.info(f"Branches archived: {archive_summary['branches_archived']}")
        logger.info(f"Branches failed: {archive_summary['branches_failed']}")
        logger.info(f"MRs archived: {archive_summary['mrs_archived']}")
        logger.info(f"MRs failed: {archive_summary['mrs_failed']}")

        if archive_summary['archived_items']:
            logger.info("Archived items:")
            for item in archive_summary['archived_items']:
                if item['type'] == 'merge_request':
                    logger.info(f"  - MR !{item['mr_iid']} ({item['project']}/{item['branch']})")
                else:
                    logger.info(f"  - Branch {item['project']}/{item['branch']}")

        if archive_summary['failed_items']:
            logger.warning("Failed items:")
            for item in archive_summary['failed_items']:
                if item['type'] == 'merge_request':
                    logger.warning(
                        f"  - MR !{item['mr_iid']} ({item['project']}/{item['branch']}): "
                        f"{item['error']}"
                    )
                else:
                    logger.warning(
                        f"  - Branch {item['project']}/{item['branch']}: {item['error']}"
                    )

    return 0


if __name__ == '__main__':
    exit(main())
