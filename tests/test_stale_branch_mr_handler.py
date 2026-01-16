"""Tests for the GitLab Stale Branch MR Handler."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import gitlab
import stale_branch_mr_handler
from stale_branch_mr_handler import ConfigurationError


class TestValidateConfig(unittest.TestCase):
    """Tests for validate_config function."""

    def test_valid_config(self):
        """Test that valid config passes validation."""
        config = {
            'gitlab': {
                'url': 'https://gitlab.example.com',
                'private_token': 'token123',
            },
            'smtp': {
                'host': 'smtp.example.com',
                'port': 587,
                'from_email': 'test@example.com',
            },
            'projects': [1, 2],
            'fallback_email': 'fallback@example.com',
        }
        # Should not raise
        stale_branch_mr_handler.validate_config(config)

    def test_empty_config(self):
        """Test that empty config raises error."""
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_mr_handler.validate_config({})
        self.assertIn('empty', str(ctx.exception).lower())

    def test_missing_gitlab_section(self):
        """Test that missing gitlab section raises error."""
        config = {
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_mr_handler.validate_config(config)
        self.assertIn('gitlab', str(ctx.exception).lower())

    def test_missing_gitlab_url(self):
        """Test that missing gitlab url raises error."""
        config = {
            'gitlab': {'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_mr_handler.validate_config(config)
        self.assertIn('url', str(ctx.exception).lower())

    def test_missing_smtp_section(self):
        """Test that missing smtp section raises error."""
        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_mr_handler.validate_config(config)
        self.assertIn('smtp', str(ctx.exception).lower())

    def test_missing_projects(self):
        """Test that missing projects raises error."""
        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_mr_handler.validate_config(config)
        self.assertIn('projects', str(ctx.exception).lower())


class TestParseDateCommit(unittest.TestCase):
    """Tests for parse_commit_date function."""

    def test_parse_z_suffix(self):
        """Test parsing date with Z suffix."""
        result = stale_branch_mr_handler.parse_commit_date('2023-01-15T10:30:00Z')
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_parse_with_offset(self):
        """Test parsing date with timezone offset."""
        result = stale_branch_mr_handler.parse_commit_date('2023-01-15T10:30:00+02:00')
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.hour, 10)

    def test_parse_with_microseconds(self):
        """Test parsing date with microseconds."""
        result = stale_branch_mr_handler.parse_commit_date('2023-01-15T10:30:00.123456+00:00')
        self.assertEqual(result.year, 2023)

    def test_parse_invalid_format(self):
        """Test that invalid format raises ValueError."""
        with self.assertRaises(ValueError):
            stale_branch_mr_handler.parse_commit_date('not-a-date')


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config function."""

    @patch('builtins.open')
    @patch('yaml.safe_load')
    @patch.object(stale_branch_mr_handler, 'validate_config')
    def test_load_config_success(self, mock_validate, mock_yaml_load, mock_open):
        """Test successful config loading."""
        expected_config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        mock_yaml_load.return_value = expected_config

        result = stale_branch_mr_handler.load_config('config.yaml')

        self.assertEqual(result, expected_config)
        mock_validate.assert_called_once_with(expected_config)

    def test_load_config_file_not_found(self):
        """Test config loading with missing file."""
        with self.assertRaises(FileNotFoundError):
            stale_branch_mr_handler.load_config('nonexistent.yaml')


class TestIsUserActive(unittest.TestCase):
    """Tests for is_user_active function."""

    def test_active_user(self):
        """Test that active user returns True."""
        mock_gl = MagicMock()
        mock_user = MagicMock()
        mock_user.state = 'active'
        mock_gl.users.list.return_value = [mock_user]

        result = stale_branch_mr_handler.is_user_active(mock_gl, 'user@example.com')

        self.assertTrue(result)
        mock_gl.users.list.assert_called_once_with(search='user@example.com', per_page=1)

    def test_inactive_user(self):
        """Test that inactive user returns False."""
        mock_gl = MagicMock()
        mock_user = MagicMock()
        mock_user.state = 'blocked'
        mock_gl.users.list.return_value = [mock_user]

        result = stale_branch_mr_handler.is_user_active(mock_gl, 'user@example.com')

        self.assertFalse(result)

    def test_user_not_found(self):
        """Test that non-existent user returns False."""
        mock_gl = MagicMock()
        mock_gl.users.list.return_value = []

        result = stale_branch_mr_handler.is_user_active(mock_gl, 'nonexistent@example.com')

        self.assertFalse(result)


class TestGetNotificationEmail(unittest.TestCase):
    """Tests for get_notification_email function."""

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_active_user_uses_own_email(self, mock_is_active):
        """Test that active user gets their own email."""
        mock_is_active.return_value = True
        mock_gl = MagicMock()

        result = stale_branch_mr_handler.get_notification_email(
            mock_gl, 'user@example.com', 'fallback@example.com'
        )

        self.assertEqual(result, 'user@example.com')

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_inactive_user_uses_fallback_email(self, mock_is_active):
        """Test that inactive user gets fallback email."""
        mock_is_active.return_value = False
        mock_gl = MagicMock()

        result = stale_branch_mr_handler.get_notification_email(
            mock_gl, 'user@example.com', 'fallback@example.com'
        )

        self.assertEqual(result, 'fallback@example.com')


class TestGetStaleBranches(unittest.TestCase):
    """Tests for get_stale_branches function."""

    def test_identifies_stale_branch(self):
        """Test that old branches are identified as stale."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.name = 'Test Project'
        mock_project.protectedbranches.list.return_value = []

        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        mock_branch = MagicMock()
        mock_branch.name = 'stale-feature'
        mock_branch.commit = {
            'committed_date': old_date,
            'author_name': 'Test User',
            'author_email': 'test@example.com',
            'committer_email': 'test@example.com',
        }

        mock_project.branches.list.return_value = [mock_branch]
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_branches(mock_gl, 1, 30)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['branch_name'], 'stale-feature')

    def test_ignores_recent_branch(self):
        """Test that recent branches are not marked as stale."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.name = 'Test Project'
        mock_project.protectedbranches.list.return_value = []

        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        mock_branch = MagicMock()
        mock_branch.name = 'active-feature'
        mock_branch.commit = {
            'committed_date': recent_date,
            'author_name': 'Test User',
            'author_email': 'test@example.com',
            'committer_email': 'test@example.com',
        }

        mock_project.branches.list.return_value = [mock_branch]
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_branches(mock_gl, 1, 30)

        self.assertEqual(len(result), 0)

    def test_ignores_protected_branch(self):
        """Test that protected branches are ignored."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.name = 'Test Project'

        mock_protected = MagicMock()
        mock_protected.name = 'main'
        mock_project.protectedbranches.list.return_value = [mock_protected]

        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        mock_branch = MagicMock()
        mock_branch.name = 'main'
        mock_branch.commit = {
            'committed_date': old_date,
            'author_name': 'Test User',
            'author_email': 'test@example.com',
            'committer_email': 'test@example.com',
        }

        mock_project.branches.list.return_value = [mock_branch]
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_branches(mock_gl, 1, 30)

        self.assertEqual(len(result), 0)


class TestGenerateEmailContent(unittest.TestCase):
    """Tests for generate_email_content function."""

    def test_generates_html_with_branches(self):
        """Test that email content includes branch information."""
        branches = [
            {
                'project_name': 'Test Project',
                'branch_name': 'feature-branch',
                'last_commit_date': '2023-01-15 10:00:00',
                'author_name': 'Test User',
            }
        ]

        result = stale_branch_mr_handler.generate_email_content(branches, 30, 4)

        self.assertIn('Test Project', result)
        self.assertIn('feature-branch', result)
        self.assertIn('Test User', result)
        self.assertIn('30 days', result)
        self.assertIn('4 weeks', result)
        self.assertIn('cleanup bot', result)

    def test_generates_html_with_multiple_branches(self):
        """Test email content with multiple branches."""
        branches = [
            {
                'project_name': 'Project 1',
                'branch_name': 'branch-1',
                'last_commit_date': '2023-01-15 10:00:00',
                'author_name': 'User 1',
            },
            {
                'project_name': 'Project 2',
                'branch_name': 'branch-2',
                'last_commit_date': '2023-01-10 10:00:00',
                'author_name': 'User 2',
            },
        ]

        result = stale_branch_mr_handler.generate_email_content(branches, 30, 4)

        self.assertIn('Project 1', result)
        self.assertIn('branch-1', result)
        self.assertIn('Project 2', result)
        self.assertIn('branch-2', result)


class TestSendEmail(unittest.TestCase):
    """Tests for send_email function."""

    def test_dry_run_does_not_send(self):
        """Test that dry run doesn't actually send email."""
        smtp_config = {
            'host': 'smtp.example.com',
            'port': 587,
            'from_email': 'test@example.com',
        }

        result = stale_branch_mr_handler.send_email(
            smtp_config,
            'recipient@example.com',
            'Test Subject',
            '<p>Test content</p>',
            dry_run=True
        )

        self.assertTrue(result)

    @patch('smtplib.SMTP')
    def test_sends_email_successfully(self, mock_smtp_class):
        """Test successful email sending."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        smtp_config = {
            'host': 'smtp.example.com',
            'port': 587,
            'use_tls': True,
            'username': 'user',
            'password': 'pass',
            'from_email': 'test@example.com',
        }

        result = stale_branch_mr_handler.send_email(
            smtp_config,
            'recipient@example.com',
            'Test Subject',
            '<p>Test content</p>',
            dry_run=False
        )

        self.assertTrue(result)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with('user', 'pass')
        mock_smtp.send_message.assert_called_once()


class TestCollectStaleBranchesByEmail(unittest.TestCase):
    """Tests for collect_stale_branches_by_email function."""

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_notification_email')
    def test_groups_branches_by_email(self, mock_get_email, mock_get_mr, mock_get_branches):
        """Test that branches are grouped by email correctly."""
        mock_gl = MagicMock()
        mock_get_branches.return_value = [
            {
                'branch_name': 'branch-1',
                'committer_email': 'user1@example.com',
                'author_email': 'user1@example.com',
            },
            {
                'branch_name': 'branch-2',
                'committer_email': 'user2@example.com',
                'author_email': 'user2@example.com',
            },
        ]
        # No merge requests for these branches
        mock_get_mr.return_value = None
        mock_get_email.side_effect = lambda gl, email, fallback: email

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_branches_by_email(mock_gl, config)

        self.assertEqual(len(result), 2)
        self.assertIn('user1@example.com', result)
        self.assertIn('user2@example.com', result)

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_notification_email')
    def test_skips_branches_without_email_and_no_fallback(self, mock_get_email, mock_get_mr, mock_get_branches):
        """Test that branches without email are skipped when no fallback is configured."""
        mock_gl = MagicMock()
        mock_get_branches.return_value = [
            {
                'branch_name': 'orphan-branch',
                'project_name': 'Test Project',
                'committer_email': '',
                'author_email': '',
            },
        ]
        # No merge requests for these branches
        mock_get_mr.return_value = None
        # No fallback email configured
        mock_get_email.return_value = ''

        config = {
            'stale_days': 30,
            'fallback_email': '',  # No fallback
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_branches_by_email(mock_gl, config)

        # Branch should be skipped
        self.assertEqual(len(result), 0)


class TestGetMergeRequestForBranch(unittest.TestCase):
    """Tests for get_merge_request_for_branch function."""

    def test_returns_mr_info_when_mr_exists(self):
        """Test that MR info is returned when an open MR exists for the branch."""
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = 'Test Project'

        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.title = 'Fix feature'
        mock_mr.web_url = 'https://gitlab.example.com/project/-/merge_requests/42'
        mock_mr.updated_at = '2023-01-15T10:30:00Z'
        mock_mr.author = {'name': 'Test User', 'email': 'test@example.com', 'username': 'testuser'}
        mock_mr.assignee = None

        mock_project.mergerequests.list.return_value = [mock_mr]

        result = stale_branch_mr_handler.get_merge_request_for_branch(mock_project, 'feature-branch')

        self.assertIsNotNone(result)
        self.assertEqual(result['iid'], 42)
        self.assertEqual(result['title'], 'Fix feature')
        self.assertEqual(result['branch_name'], 'feature-branch')
        self.assertEqual(result['author_name'], 'Test User')

    def test_returns_none_when_no_mr_exists(self):
        """Test that None is returned when no open MR exists for the branch."""
        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = []

        result = stale_branch_mr_handler.get_merge_request_for_branch(mock_project, 'orphan-branch')

        self.assertIsNone(result)

    def test_uses_assignee_email_when_available(self):
        """Test that assignee email is used when available."""
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = 'Test Project'

        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.title = 'Fix feature'
        mock_mr.web_url = 'https://gitlab.example.com/project/-/merge_requests/42'
        mock_mr.updated_at = '2023-01-15T10:30:00Z'
        mock_mr.author = {'name': 'Author User', 'email': 'author@example.com', 'username': 'author'}
        mock_mr.assignee = {'name': 'Assignee User', 'email': 'assignee@example.com', 'username': 'assignee'}

        mock_project.mergerequests.list.return_value = [mock_mr]

        result = stale_branch_mr_handler.get_merge_request_for_branch(mock_project, 'feature-branch')

        self.assertIsNotNone(result)
        self.assertEqual(result['assignee_email'], 'assignee@example.com')
        self.assertEqual(result['author_email'], 'author@example.com')


class TestCollectStaleItemsByEmail(unittest.TestCase):
    """Tests for collect_stale_items_by_email function."""

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_mr_notification_email')
    def test_uses_mr_instead_of_branch_when_mr_exists(self, mock_get_mr_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that MR is used instead of branch when an open MR exists."""
        mock_gl = MagicMock()
        # Use an old date to make the MR stale
        old_date = datetime.now(timezone.utc) - timedelta(days=60)

        # Stale MRs are now fetched directly via get_stale_merge_requests
        stale_mr = {
            'iid': 42,
            'title': 'Fix feature',
            'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
            'branch_name': 'feature-branch',
            'project_id': 1,
            'project_name': 'Test Project',
            'assignee_email': '',
            'author_email': 'mr-author@example.com',
            'author_name': 'MR Author',
            'last_updated': '2023-01-15 10:30:00',
            'updated_at': old_date,
        }
        mock_get_stale_mrs.return_value = [stale_mr]

        # Stale branches that have MRs should be skipped
        mock_get_branches.return_value = [
            {
                'branch_name': 'feature-branch',
                'project_name': 'Test Project',
                'committer_email': 'committer@example.com',
                'author_email': 'committer@example.com',
            },
        ]
        # This branch has an MR, so get_merge_request_for_branch won't be called for it
        mock_get_mr.return_value = None
        mock_get_mr_email.return_value = 'mr-author@example.com'

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # Should have MR, not branch
        self.assertEqual(len(result), 1)
        self.assertIn('mr-author@example.com', result)
        items = result['mr-author@example.com']
        self.assertEqual(len(items['merge_requests']), 1)
        self.assertEqual(len(items['branches']), 0)
        self.assertEqual(items['merge_requests'][0]['iid'], 42)

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_mr_notification_email')
    def test_uses_assignee_email_for_mr_notification(self, mock_get_mr_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that MR assignee email is used for notification when available."""
        mock_gl = MagicMock()
        # Use an old date to make the MR stale
        old_date = datetime.now(timezone.utc) - timedelta(days=60)

        stale_mr = {
            'iid': 42,
            'title': 'Fix feature',
            'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
            'branch_name': 'feature-branch',
            'project_id': 1,
            'project_name': 'Test Project',
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
            'author_name': 'MR Author',
            'last_updated': '2023-01-15 10:30:00',
            'updated_at': old_date,
        }
        mock_get_stale_mrs.return_value = [stale_mr]
        mock_get_branches.return_value = []
        mock_get_mr.return_value = None
        mock_get_mr_email.return_value = 'assignee@example.com'

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # Should use assignee email
        self.assertEqual(len(result), 1)
        self.assertIn('assignee@example.com', result)

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_mr_notification_email')
    def test_uses_fallback_when_no_mr_email(self, mock_get_mr_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that fallback email is used when MR has no assignee or author email."""
        mock_gl = MagicMock()
        # Use an old date to make the MR stale
        old_date = datetime.now(timezone.utc) - timedelta(days=60)

        stale_mr = {
            'iid': 42,
            'title': 'Fix feature',
            'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
            'branch_name': 'feature-branch',
            'project_id': 1,
            'project_name': 'Test Project',
            'assignee_email': '',
            'author_email': '',
            'author_name': 'Unknown',
            'last_updated': '2023-01-15 10:30:00',
            'updated_at': old_date,
        }
        mock_get_stale_mrs.return_value = [stale_mr]
        mock_get_branches.return_value = []
        mock_get_mr.return_value = None
        mock_get_mr_email.return_value = 'fallback@example.com'

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # Should use fallback email
        self.assertEqual(len(result), 1)
        self.assertIn('fallback@example.com', result)


class TestGenerateEmailContentWithMRs(unittest.TestCase):
    """Tests for generate_email_content with merge requests."""

    def test_generates_html_with_merge_requests(self):
        """Test that email content includes merge request information."""
        branches = []
        merge_requests = [
            {
                'project_name': 'Test Project',
                'branch_name': 'feature-branch',
                'iid': 42,
                'title': 'Fix feature',
                'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
                'last_updated': '2023-01-15 10:00:00',
                'author_name': 'Test User',
            }
        ]

        result = stale_branch_mr_handler.generate_email_content(
            branches, 30, 4, merge_requests
        )

        self.assertIn('Test Project', result)
        self.assertIn('feature-branch', result)
        self.assertIn('!42', result)
        self.assertIn('Fix feature', result)
        self.assertIn('Stale Merge Requests', result)

    def test_generates_html_with_both_branches_and_mrs(self):
        """Test email content with both branches and merge requests."""
        branches = [
            {
                'project_name': 'Project 1',
                'branch_name': 'old-branch',
                'last_commit_date': '2023-01-10 10:00:00',
                'author_name': 'User 1',
            }
        ]
        merge_requests = [
            {
                'project_name': 'Project 2',
                'branch_name': 'feature-branch',
                'iid': 42,
                'title': 'Fix feature',
                'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
                'last_updated': '2023-01-15 10:00:00',
                'author_name': 'User 2',
            }
        ]

        result = stale_branch_mr_handler.generate_email_content(
            branches, 30, 4, merge_requests
        )

        self.assertIn('old-branch', result)
        self.assertIn('Stale Branches', result)
        self.assertIn('!42', result)
        self.assertIn('Stale Merge Requests', result)


class TestGetMrNotificationEmail(unittest.TestCase):
    """Tests for get_mr_notification_email function."""

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_uses_active_assignee_email(self, mock_is_active):
        """Test that active assignee email is used first."""
        mock_is_active.return_value = True
        mock_gl = MagicMock()
        mr_info = {
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
        }

        result = stale_branch_mr_handler.get_mr_notification_email(
            mock_gl, mr_info, 'fallback@example.com'
        )

        self.assertEqual(result, 'assignee@example.com')
        mock_is_active.assert_called_once_with(mock_gl, 'assignee@example.com')

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_uses_author_email_when_assignee_inactive(self, mock_is_active):
        """Test that author email is used when assignee is inactive."""
        # First call for assignee returns False, second for author returns True
        mock_is_active.side_effect = [False, True]
        mock_gl = MagicMock()
        mr_info = {
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
        }

        result = stale_branch_mr_handler.get_mr_notification_email(
            mock_gl, mr_info, 'fallback@example.com'
        )

        self.assertEqual(result, 'author@example.com')
        self.assertEqual(mock_is_active.call_count, 2)

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_uses_fallback_when_both_inactive(self, mock_is_active):
        """Test that fallback email is used when both assignee and author are inactive."""
        mock_is_active.return_value = False
        mock_gl = MagicMock()
        mr_info = {
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
        }

        result = stale_branch_mr_handler.get_mr_notification_email(
            mock_gl, mr_info, 'fallback@example.com'
        )

        self.assertEqual(result, 'fallback@example.com')

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    def test_skips_to_author_when_no_assignee(self, mock_is_active):
        """Test that author is used when there's no assignee."""
        mock_is_active.return_value = True
        mock_gl = MagicMock()
        mr_info = {
            'assignee_email': '',
            'author_email': 'author@example.com',
        }

        result = stale_branch_mr_handler.get_mr_notification_email(
            mock_gl, mr_info, 'fallback@example.com'
        )

        self.assertEqual(result, 'author@example.com')
        mock_is_active.assert_called_once_with(mock_gl, 'author@example.com')

    @patch.object(stale_branch_mr_handler, 'is_user_active')
    @patch.object(stale_branch_mr_handler, 'get_user_email_by_username')
    def test_uses_username_to_get_assignee_email(self, mock_get_email, mock_is_active):
        """Test that assignee username is used to get email when email is missing."""
        mock_get_email.return_value = 'assignee@example.com'
        mock_is_active.return_value = True
        mock_gl = MagicMock()
        mr_info = {
            'assignee_email': '',
            'assignee_username': 'assignee_user',
            'author_email': 'author@example.com',
        }

        result = stale_branch_mr_handler.get_mr_notification_email(
            mock_gl, mr_info, 'fallback@example.com'
        )

        self.assertEqual(result, 'assignee@example.com')
        mock_get_email.assert_called_once_with(mock_gl, 'assignee_user')


class TestMrStalenessChecking(unittest.TestCase):
    """Tests for MR staleness checking based on MR activity."""

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_mr_notification_email')
    def test_skips_mr_with_recent_activity(self, mock_get_mr_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that MR with recent activity is not considered stale."""
        mock_gl = MagicMock()
        # Use a recent date so the MR is NOT stale
        recent_date = datetime.now(timezone.utc) - timedelta(days=5)

        # No stale MRs (MR has recent activity, so it's not returned by get_stale_merge_requests)
        mock_get_stale_mrs.return_value = []

        # Stale branch exists
        mock_get_branches.return_value = [
            {
                'branch_name': 'feature-branch',
                'project_name': 'Test Project',
                'committer_email': 'committer@example.com',
                'author_email': 'committer@example.com',
            },
        ]
        # Branch has an active MR (not stale)
        mock_get_mr.return_value = {
            'iid': 42,
            'title': 'Fix feature',
            'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
            'branch_name': 'feature-branch',
            'project_id': 1,
            'project_name': 'Test Project',
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
            'author_name': 'MR Author',
            'last_updated': '2023-01-15 10:30:00',
            'updated_at': recent_date,  # Recent activity
        }

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # MR should be skipped because it has recent activity
        # Branch should also be skipped because it has an active MR
        self.assertEqual(len(result), 0)
        # get_mr_notification_email should not be called since no stale MRs found
        mock_get_mr_email.assert_not_called()

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_mr_notification_email')
    def test_includes_mr_with_old_activity(self, mock_get_mr_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that MR with old activity is considered stale."""
        mock_gl = MagicMock()
        # Use an old date so the MR IS stale
        old_date = datetime.now(timezone.utc) - timedelta(days=60)

        # Stale MR found directly
        stale_mr = {
            'iid': 42,
            'title': 'Fix feature',
            'web_url': 'https://gitlab.example.com/project/-/merge_requests/42',
            'branch_name': 'feature-branch',
            'project_id': 1,
            'project_name': 'Test Project',
            'assignee_email': 'assignee@example.com',
            'author_email': 'author@example.com',
            'author_name': 'MR Author',
            'last_updated': '2023-01-15 10:30:00',
            'updated_at': old_date,  # Old activity - stale
        }
        mock_get_stale_mrs.return_value = [stale_mr]
        mock_get_branches.return_value = []
        mock_get_mr.return_value = None
        mock_get_mr_email.return_value = 'assignee@example.com'

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # MR should be included because it's stale
        self.assertEqual(len(result), 1)
        self.assertIn('assignee@example.com', result)
        items = result['assignee@example.com']
        self.assertEqual(len(items['merge_requests']), 1)


class TestGetMrLastActivityDate(unittest.TestCase):
    """Tests for get_mr_last_activity_date function."""

    def test_uses_mr_updated_at_when_no_notes(self):
        """Test that MR updated_at is used when there are no notes."""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.updated_at = '2023-01-15T10:30:00Z'

        # No notes
        mock_project.mergerequests.get.return_value.notes.list.return_value = []

        result = stale_branch_mr_handler.get_mr_last_activity_date(mock_project, mock_mr)

        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_uses_note_date_when_more_recent(self):
        """Test that note date is used when it's more recent than MR updated_at."""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.updated_at = '2023-01-15T10:30:00Z'

        # Note with more recent date
        mock_note = MagicMock()
        mock_note.updated_at = '2023-02-20T15:00:00Z'
        mock_project.mergerequests.get.return_value.notes.list.return_value = [mock_note]

        result = stale_branch_mr_handler.get_mr_last_activity_date(mock_project, mock_mr)

        self.assertIsNotNone(result)
        # Should use the note date (Feb 20) which is more recent than MR date (Jan 15)
        self.assertEqual(result.month, 2)
        self.assertEqual(result.day, 20)

    def test_handles_missing_mr_updated_at(self):
        """Test handling when MR updated_at cannot be parsed."""
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.updated_at = 'invalid-date'

        # Note with valid date
        mock_note = MagicMock()
        mock_note.updated_at = '2023-02-20T15:00:00Z'
        mock_project.mergerequests.get.return_value.notes.list.return_value = [mock_note]

        result = stale_branch_mr_handler.get_mr_last_activity_date(mock_project, mock_mr)

        # Should still return the note date
        self.assertIsNotNone(result)
        self.assertEqual(result.month, 2)


class TestGetStaleMergeRequests(unittest.TestCase):
    """Tests for get_stale_merge_requests function."""

    def test_identifies_stale_mr(self):
        """Test that old MRs are identified as stale."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = 'Test Project'

        # Create mock MR with old activity
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.title = 'Old MR'
        mock_mr.web_url = 'https://gitlab.example.com/project/-/merge_requests/42'
        mock_mr.updated_at = old_date
        mock_mr.source_branch = 'feature-branch'
        mock_mr.author = {'name': 'Test User', 'email': 'test@example.com', 'username': 'testuser'}
        mock_mr.assignee = None

        mock_project.mergerequests.list.return_value = [mock_mr]
        mock_project.mergerequests.get.return_value.notes.list.return_value = []
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_merge_requests(mock_gl, 1, 30)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['iid'], 42)
        self.assertEqual(result[0]['branch_name'], 'feature-branch')

    def test_ignores_recent_mr(self):
        """Test that recent MRs are not marked as stale."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = 'Test Project'

        # Create mock MR with recent activity
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.title = 'Recent MR'
        mock_mr.web_url = 'https://gitlab.example.com/project/-/merge_requests/42'
        mock_mr.updated_at = recent_date
        mock_mr.source_branch = 'feature-branch'
        mock_mr.author = {'name': 'Test User', 'email': 'test@example.com', 'username': 'testuser'}
        mock_mr.assignee = None

        mock_project.mergerequests.list.return_value = [mock_mr]
        mock_project.mergerequests.get.return_value.notes.list.return_value = []
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_merge_requests(mock_gl, 1, 30)

        self.assertEqual(len(result), 0)

    def test_mr_with_recent_note_not_stale(self):
        """Test that MR with recent note activity is not considered stale."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = 'Test Project'

        # Create mock MR with old updated_at but recent note
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        recent_note_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.title = 'MR with recent comment'
        mock_mr.web_url = 'https://gitlab.example.com/project/-/merge_requests/42'
        mock_mr.updated_at = old_date  # Old MR metadata update
        mock_mr.source_branch = 'feature-branch'
        mock_mr.author = {'name': 'Test User', 'email': 'test@example.com', 'username': 'testuser'}
        mock_mr.assignee = None

        # Recent note/comment
        mock_note = MagicMock()
        mock_note.updated_at = recent_note_date

        mock_project.mergerequests.list.return_value = [mock_mr]
        mock_project.mergerequests.get.return_value.notes.list.return_value = [mock_note]
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.get_stale_merge_requests(mock_gl, 1, 30)

        # MR should NOT be stale because of recent note activity
        self.assertEqual(len(result), 0)


class TestBranchWithoutMrNotification(unittest.TestCase):
    """Tests for branch notification when no MR exists."""

    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    @patch.object(stale_branch_mr_handler, 'get_notification_email')
    def test_notifies_stale_branch_without_mr(self, mock_get_email, mock_get_mr, mock_get_stale_mrs, mock_get_branches):
        """Test that stale branches without MRs are included in notifications."""
        mock_gl = MagicMock()

        # No stale MRs
        mock_get_stale_mrs.return_value = []

        # Stale branch exists
        mock_get_branches.return_value = [
            {
                'branch_name': 'orphan-branch',
                'project_name': 'Test Project',
                'project_id': 1,
                'committer_email': 'user@example.com',
                'author_email': 'user@example.com',
                'last_commit_date': '2023-01-15 10:00:00',
                'author_name': 'Test User',
            },
        ]

        # No MR for this branch
        mock_get_mr.return_value = None
        mock_get_email.return_value = 'user@example.com'

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_mr_handler.collect_stale_items_by_email(mock_gl, config)

        # Should have the branch notification
        self.assertEqual(len(result), 1)
        self.assertIn('user@example.com', result)
        items = result['user@example.com']
        self.assertEqual(len(items['branches']), 1)
        self.assertEqual(len(items['merge_requests']), 0)
        self.assertEqual(items['branches'][0]['branch_name'], 'orphan-branch')


class TestNotificationDatabase(unittest.TestCase):
    """Tests for notification database functions."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_notifications.db')

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_init_database_creates_tables(self):
        """Test that init_database creates the required tables."""
        import sqlite3
        stale_branch_mr_handler.init_database(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Check that the table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='notification_history'"
            )
            result = cursor.fetchone()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'notification_history')

    def test_record_and_get_notification(self):
        """Test recording and retrieving notification history."""
        stale_branch_mr_handler.init_database(self.db_path)

        # Record a notification
        notification_time = datetime.now(timezone.utc)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'feature-branch',
            notification_time
        )

        # Retrieve it
        result = stale_branch_mr_handler.get_last_notification_date(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'feature-branch'
        )

        self.assertIsNotNone(result)
        # Compare timestamps (allowing for some timezone handling differences)
        self.assertEqual(result.year, notification_time.year)
        self.assertEqual(result.month, notification_time.month)
        self.assertEqual(result.day, notification_time.day)

    def test_get_nonexistent_notification_returns_none(self):
        """Test that getting a nonexistent notification returns None."""
        stale_branch_mr_handler.init_database(self.db_path)

        result = stale_branch_mr_handler.get_last_notification_date(
            self.db_path,
            'nonexistent@example.com',
            'branch',
            999,
            'nonexistent-branch'
        )

        self.assertIsNone(result)

    def test_record_updates_existing_notification(self):
        """Test that recording again updates the last_notified_at."""
        stale_branch_mr_handler.init_database(self.db_path)

        # Record initial notification
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'feature-branch',
            old_time
        )

        # Record again with new time
        new_time = datetime.now(timezone.utc)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'feature-branch',
            new_time
        )

        # Retrieve and verify it's the new time
        result = stale_branch_mr_handler.get_last_notification_date(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'feature-branch'
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.day, new_time.day)


class TestShouldSendNotification(unittest.TestCase):
    """Tests for should_send_notification function."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_notifications.db')
        stale_branch_mr_handler.init_database(self.db_path)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_should_notify_for_new_items(self):
        """Test that notification is sent for new items."""
        items = {
            'branches': [{
                'project_id': 123,
                'branch_name': 'new-branch',
            }],
            'merge_requests': []
        }

        result = stale_branch_mr_handler.should_send_notification(
            self.db_path,
            'test@example.com',
            items,
            frequency_days=7
        )

        self.assertTrue(result)

    def test_should_not_notify_recently_notified_items(self):
        """Test that notification is not sent for recently notified items."""
        # Record a recent notification
        recent_time = datetime.now(timezone.utc) - timedelta(days=2)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'old-branch',
            recent_time
        )

        items = {
            'branches': [{
                'project_id': 123,
                'branch_name': 'old-branch',
            }],
            'merge_requests': []
        }

        result = stale_branch_mr_handler.should_send_notification(
            self.db_path,
            'test@example.com',
            items,
            frequency_days=7
        )

        self.assertFalse(result)

    def test_should_notify_after_frequency_period(self):
        """Test that notification is sent after frequency period has passed."""
        # Record an old notification
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'old-branch',
            old_time
        )

        items = {
            'branches': [{
                'project_id': 123,
                'branch_name': 'old-branch',
            }],
            'merge_requests': []
        }

        result = stale_branch_mr_handler.should_send_notification(
            self.db_path,
            'test@example.com',
            items,
            frequency_days=7
        )

        self.assertTrue(result)

    def test_should_notify_when_new_item_found(self):
        """Test that notification is sent when a new item is found alongside old items."""
        # Record a recent notification for an old item
        recent_time = datetime.now(timezone.utc) - timedelta(days=2)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'old-branch',
            recent_time
        )

        # Items include both old (recently notified) and new branches
        items = {
            'branches': [
                {'project_id': 123, 'branch_name': 'old-branch'},
                {'project_id': 123, 'branch_name': 'new-branch'},  # New item
            ],
            'merge_requests': []
        }

        result = stale_branch_mr_handler.should_send_notification(
            self.db_path,
            'test@example.com',
            items,
            frequency_days=7
        )

        # Should send notification because of the new item
        self.assertTrue(result)

    def test_should_not_notify_empty_items(self):
        """Test that notification is not sent for empty items."""
        items = {
            'branches': [],
            'merge_requests': []
        }

        result = stale_branch_mr_handler.should_send_notification(
            self.db_path,
            'test@example.com',
            items,
            frequency_days=7
        )

        self.assertFalse(result)


class TestRecordNotificationsForItems(unittest.TestCase):
    """Tests for record_notifications_for_items function."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_notifications.db')
        stale_branch_mr_handler.init_database(self.db_path)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_records_all_branches(self):
        """Test that all branches are recorded."""
        items = {
            'branches': [
                {'project_id': 123, 'branch_name': 'branch-1'},
                {'project_id': 123, 'branch_name': 'branch-2'},
            ],
            'merge_requests': []
        }

        stale_branch_mr_handler.record_notifications_for_items(
            self.db_path,
            'test@example.com',
            items
        )

        # Verify both branches were recorded
        result1 = stale_branch_mr_handler.get_last_notification_date(
            self.db_path, 'test@example.com', 'branch', 123, 'branch-1'
        )
        result2 = stale_branch_mr_handler.get_last_notification_date(
            self.db_path, 'test@example.com', 'branch', 123, 'branch-2'
        )

        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)

    def test_records_all_merge_requests(self):
        """Test that all merge requests are recorded."""
        items = {
            'branches': [],
            'merge_requests': [
                {'project_id': 123, 'iid': 42},
                {'project_id': 123, 'iid': 43},
            ]
        }

        stale_branch_mr_handler.record_notifications_for_items(
            self.db_path,
            'test@example.com',
            items
        )

        # Verify both MRs were recorded
        result1 = stale_branch_mr_handler.get_last_notification_date(
            self.db_path, 'test@example.com', 'merge_request', 123, 42
        )
        result2 = stale_branch_mr_handler.get_last_notification_date(
            self.db_path, 'test@example.com', 'merge_request', 123, 43
        )

        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)


class TestNotifyWithThrottling(unittest.TestCase):
    """Tests for notify_stale_branches with throttling."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_notifications.db')

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'collect_stale_items_by_email')
    @patch.object(stale_branch_mr_handler, 'send_email')
    def test_skips_recently_notified_recipients(self, mock_send, mock_collect, mock_gl):
        """Test that recently notified recipients are skipped."""
        # Set up database with recent notification
        stale_branch_mr_handler.init_database(self.db_path)
        recent_time = datetime.now(timezone.utc) - timedelta(days=2)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'old-branch',
            recent_time
        )

        # Set up mocks
        mock_gl.return_value = MagicMock()
        mock_collect.return_value = {
            'test@example.com': {
                'branches': [{'project_id': 123, 'branch_name': 'old-branch'}],
                'merge_requests': []
            }
        }
        mock_send.return_value = True

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [123],
            'stale_days': 30,
            'notification_frequency_days': 7,
            'database_path': self.db_path,
        }

        result = stale_branch_mr_handler.notify_stale_branches(config, dry_run=False)

        # Should skip the email
        self.assertEqual(result['emails_skipped'], 1)
        self.assertEqual(result['emails_sent'], 0)
        mock_send.assert_not_called()

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'collect_stale_items_by_email')
    @patch.object(stale_branch_mr_handler, 'send_email')
    def test_sends_email_for_new_items(self, mock_send, mock_collect, mock_gl):
        """Test that new items trigger email sending."""
        stale_branch_mr_handler.init_database(self.db_path)

        # Set up mocks
        mock_gl.return_value = MagicMock()
        mock_collect.return_value = {
            'test@example.com': {
                'branches': [{'project_id': 123, 'branch_name': 'new-branch'}],
                'merge_requests': []
            }
        }
        mock_send.return_value = True

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [123],
            'stale_days': 30,
            'notification_frequency_days': 7,
            'database_path': self.db_path,
        }

        result = stale_branch_mr_handler.notify_stale_branches(config, dry_run=False)

        # Should send the email
        self.assertEqual(result['emails_sent'], 1)
        self.assertEqual(result['emails_skipped'], 0)
        mock_send.assert_called_once()

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'collect_stale_items_by_email')
    @patch.object(stale_branch_mr_handler, 'send_email')
    def test_sends_when_new_item_found_with_old_items(self, mock_send, mock_collect, mock_gl):
        """Test that new items trigger sending even if old items were recently notified."""
        stale_branch_mr_handler.init_database(self.db_path)

        # Record recent notification for old branch
        recent_time = datetime.now(timezone.utc) - timedelta(days=2)
        stale_branch_mr_handler.record_notification(
            self.db_path,
            'test@example.com',
            'branch',
            123,
            'old-branch',
            recent_time
        )

        # Set up mocks with both old and new branches
        mock_gl.return_value = MagicMock()
        mock_collect.return_value = {
            'test@example.com': {
                'branches': [
                    {'project_id': 123, 'branch_name': 'old-branch'},
                    {'project_id': 123, 'branch_name': 'new-branch'},
                ],
                'merge_requests': []
            }
        }
        mock_send.return_value = True

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [123],
            'stale_days': 30,
            'notification_frequency_days': 7,
            'database_path': self.db_path,
        }

        result = stale_branch_mr_handler.notify_stale_branches(config, dry_run=False)

        # Should send the email because of the new item
        self.assertEqual(result['emails_sent'], 1)
        self.assertEqual(result['emails_skipped'], 0)
        mock_send.assert_called_once()


# =============================================================================
# Tests for Automatic Archiving Functionality
# =============================================================================


class TestIsReadyForArchiving(unittest.TestCase):
    """Tests for is_ready_for_archiving function."""

    def test_item_old_enough_for_archiving(self):
        """Test that item older than stale_days + cleanup_weeks is ready for archiving."""
        # Item is 60 days old, threshold is 30 + 28 = 58 days
        item_age = datetime.now(timezone.utc) - timedelta(days=60)
        result = stale_branch_mr_handler.is_ready_for_archiving(item_age, 30, 4)
        self.assertTrue(result)

    def test_item_not_old_enough_for_archiving(self):
        """Test that item younger than threshold is not ready for archiving."""
        # Item is 40 days old, threshold is 30 + 28 = 58 days
        item_age = datetime.now(timezone.utc) - timedelta(days=40)
        result = stale_branch_mr_handler.is_ready_for_archiving(item_age, 30, 4)
        self.assertFalse(result)

    def test_item_exactly_at_threshold(self):
        """Test item exactly at the threshold."""
        # Item is exactly 58 days old, threshold is 30 + 28 = 58 days
        item_age = datetime.now(timezone.utc) - timedelta(days=58, hours=1)
        result = stale_branch_mr_handler.is_ready_for_archiving(item_age, 30, 4)
        self.assertTrue(result)

    def test_none_item_age_returns_false(self):
        """Test that None item_age returns False."""
        result = stale_branch_mr_handler.is_ready_for_archiving(None, 30, 4)
        self.assertFalse(result)


class TestExportBranchToArchive(unittest.TestCase):
    """Tests for export_branch_to_archive function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_export_creates_archive_file(self):
        """Test that export creates an archive file."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.repository_archive.return_value = b'fake archive data'
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.export_branch_to_archive(
            mock_gl, 123, 'feature-branch', self.temp_dir, 'Test Project'
        )

        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))
        self.assertTrue(result.endswith('.tar.gz'))
        mock_project.repository_archive.assert_called_once_with(
            sha='feature-branch', format='tar.gz'
        )

    def test_export_handles_gitlab_error(self):
        """Test that export handles GitLab errors gracefully."""
        mock_gl = MagicMock()
        mock_gl.projects.get.side_effect = gitlab.exceptions.GitlabError("API Error")

        result = stale_branch_mr_handler.export_branch_to_archive(
            mock_gl, 123, 'feature-branch', self.temp_dir, 'Test Project'
        )

        self.assertIsNone(result)

    def test_export_sanitizes_filenames(self):
        """Test that special characters in names are sanitized."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.repository_archive.return_value = b'fake archive data'
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.export_branch_to_archive(
            mock_gl, 123, 'feature/branch-name', self.temp_dir, 'Test Project!'
        )

        self.assertIsNotNone(result)
        # Check that special characters are replaced
        self.assertNotIn('/', os.path.basename(result))
        self.assertNotIn('!', os.path.basename(result))


class TestCloseMergeRequest(unittest.TestCase):
    """Tests for close_merge_request function."""

    def test_close_mr_dry_run(self):
        """Test that dry run doesn't actually close MR."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_project.mergerequests.get.return_value = mock_mr

        result = stale_branch_mr_handler.close_merge_request(
            mock_gl, 123, 42, dry_run=True
        )

        self.assertTrue(result)
        mock_mr.save.assert_not_called()

    def test_close_mr_adds_note_and_closes(self):
        """Test that close_merge_request adds a note and closes the MR."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_project.mergerequests.get.return_value = mock_mr

        result = stale_branch_mr_handler.close_merge_request(
            mock_gl, 123, 42, dry_run=False
        )

        self.assertTrue(result)
        mock_mr.notes.create.assert_called_once()
        self.assertEqual(mock_mr.state_event, 'close')
        mock_mr.save.assert_called_once()

    def test_close_mr_handles_error(self):
        """Test that errors are handled gracefully."""
        mock_gl = MagicMock()
        mock_gl.projects.get.side_effect = gitlab.exceptions.GitlabError("API Error")

        result = stale_branch_mr_handler.close_merge_request(
            mock_gl, 123, 42, dry_run=False
        )

        self.assertFalse(result)


class TestDeleteBranch(unittest.TestCase):
    """Tests for delete_branch function."""

    def test_delete_branch_dry_run(self):
        """Test that dry run doesn't actually delete branch."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.delete_branch(
            mock_gl, 123, 'feature-branch', dry_run=True
        )

        self.assertTrue(result)
        mock_project.branches.delete.assert_not_called()

    def test_delete_branch_success(self):
        """Test successful branch deletion."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.delete_branch(
            mock_gl, 123, 'feature-branch', dry_run=False
        )

        self.assertTrue(result)
        mock_project.branches.delete.assert_called_once_with('feature-branch')

    def test_delete_branch_handles_error(self):
        """Test that errors are handled gracefully."""
        mock_gl = MagicMock()
        mock_project = MagicMock()
        mock_project.branches.delete.side_effect = gitlab.exceptions.GitlabError("API Error")
        mock_gl.projects.get.return_value = mock_project

        result = stale_branch_mr_handler.delete_branch(
            mock_gl, 123, 'feature-branch', dry_run=False
        )

        self.assertFalse(result)


class TestArchiveStaleBranch(unittest.TestCase):
    """Tests for archive_stale_branch function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_branch_success(self, mock_delete, mock_export):
        """Test successful branch archiving."""
        mock_gl = MagicMock()
        mock_export.return_value = os.path.join(self.temp_dir, 'archive.tar.gz')
        mock_delete.return_value = True

        result = stale_branch_mr_handler.archive_stale_branch(
            mock_gl, 123, 'Test Project', 'feature-branch', self.temp_dir, dry_run=False
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['archived'])
        self.assertTrue(result['deleted'])
        self.assertIsNone(result['error'])

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_branch_export_fails_aborts_delete(self, mock_delete, mock_export):
        """Test that failed export aborts deletion."""
        mock_gl = MagicMock()
        mock_export.return_value = None  # Export failed

        result = stale_branch_mr_handler.archive_stale_branch(
            mock_gl, 123, 'Test Project', 'feature-branch', self.temp_dir, dry_run=False
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['archived'])
        self.assertFalse(result['deleted'])
        self.assertIsNotNone(result['error'])
        mock_delete.assert_not_called()  # Delete should not be called

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_branch_dry_run(self, mock_delete, mock_export):
        """Test dry run mode."""
        mock_gl = MagicMock()
        mock_delete.return_value = True

        result = stale_branch_mr_handler.archive_stale_branch(
            mock_gl, 123, 'Test Project', 'feature-branch', self.temp_dir, dry_run=True
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['archived'])
        mock_export.assert_not_called()  # Should not actually export in dry run


class TestArchiveStaleMr(unittest.TestCase):
    """Tests for archive_stale_mr function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'close_merge_request')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_mr_success(self, mock_delete, mock_close, mock_export):
        """Test successful MR archiving."""
        mock_gl = MagicMock()
        mock_export.return_value = os.path.join(self.temp_dir, 'archive.tar.gz')
        mock_close.return_value = True
        mock_delete.return_value = True

        result = stale_branch_mr_handler.archive_stale_mr(
            mock_gl, 123, 'Test Project', 'feature-branch', 42, self.temp_dir, dry_run=False
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['archived'])
        self.assertTrue(result['mr_closed'])
        self.assertTrue(result['deleted'])
        self.assertIsNone(result['error'])

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'close_merge_request')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_mr_export_fails_aborts_all(self, mock_delete, mock_close, mock_export):
        """Test that failed export aborts MR close and deletion."""
        mock_gl = MagicMock()
        mock_export.return_value = None  # Export failed

        result = stale_branch_mr_handler.archive_stale_mr(
            mock_gl, 123, 'Test Project', 'feature-branch', 42, self.temp_dir, dry_run=False
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['archived'])
        self.assertFalse(result['mr_closed'])
        self.assertFalse(result['deleted'])
        self.assertIsNotNone(result['error'])
        mock_close.assert_not_called()
        mock_delete.assert_not_called()

    @patch.object(stale_branch_mr_handler, 'export_branch_to_archive')
    @patch.object(stale_branch_mr_handler, 'close_merge_request')
    @patch.object(stale_branch_mr_handler, 'delete_branch')
    def test_archive_mr_dry_run(self, mock_delete, mock_close, mock_export):
        """Test dry run mode."""
        mock_gl = MagicMock()
        mock_close.return_value = True
        mock_delete.return_value = True

        result = stale_branch_mr_handler.archive_stale_mr(
            mock_gl, 123, 'Test Project', 'feature-branch', 42, self.temp_dir, dry_run=True
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['archived'])
        mock_export.assert_not_called()  # Should not actually export in dry run


class TestGetBranchesReadyForArchiving(unittest.TestCase):
    """Tests for get_branches_ready_for_archiving function."""

    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    def test_identifies_mr_ready_for_archiving(self, mock_get_mr, mock_get_branches, mock_get_stale_mrs):
        """Test that MRs ready for archiving are identified."""
        mock_gl = MagicMock()

        # MR is old enough for archiving (60 days, threshold is 58)
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        mock_get_stale_mrs.return_value = [
            {
                'iid': 42,
                'branch_name': 'old-feature',
                'project_id': 123,
                'project_name': 'Test Project',
                'updated_at': old_date,
            }
        ]
        mock_get_branches.return_value = []
        mock_get_mr.return_value = None

        config = {
            'stale_days': 30,
            'cleanup_weeks': 4,
            'projects': [123],
        }

        branches, mrs = stale_branch_mr_handler.get_branches_ready_for_archiving(mock_gl, config)

        self.assertEqual(len(mrs), 1)
        self.assertEqual(mrs[0]['iid'], 42)
        self.assertEqual(len(branches), 0)

    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    def test_excludes_mr_not_ready_for_archiving(self, mock_get_mr, mock_get_branches, mock_get_stale_mrs):
        """Test that MRs not ready for archiving are excluded."""
        mock_gl = MagicMock()

        # MR is not old enough for archiving (40 days, threshold is 58)
        recent_date = datetime.now(timezone.utc) - timedelta(days=40)
        mock_get_stale_mrs.return_value = [
            {
                'iid': 42,
                'branch_name': 'recent-feature',
                'project_id': 123,
                'project_name': 'Test Project',
                'updated_at': recent_date,
            }
        ]
        mock_get_branches.return_value = []
        mock_get_mr.return_value = None

        config = {
            'stale_days': 30,
            'cleanup_weeks': 4,
            'projects': [123],
        }

        branches, mrs = stale_branch_mr_handler.get_branches_ready_for_archiving(mock_gl, config)

        self.assertEqual(len(mrs), 0)
        self.assertEqual(len(branches), 0)

    @patch.object(stale_branch_mr_handler, 'get_stale_merge_requests')
    @patch.object(stale_branch_mr_handler, 'get_stale_branches')
    @patch.object(stale_branch_mr_handler, 'get_merge_request_for_branch')
    def test_identifies_branch_ready_for_archiving(self, mock_get_mr, mock_get_branches, mock_get_stale_mrs):
        """Test that branches ready for archiving are identified."""
        mock_gl = MagicMock()
        mock_get_stale_mrs.return_value = []

        # Branch is old enough for archiving (60 days, threshold is 58)
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
        mock_get_branches.return_value = [
            {
                'branch_name': 'old-feature',
                'project_id': 123,
                'project_name': 'Test Project',
                'last_commit_date': old_date,
            }
        ]
        mock_get_mr.return_value = None  # No MR for this branch

        config = {
            'stale_days': 30,
            'cleanup_weeks': 4,
            'projects': [123],
        }

        branches, mrs = stale_branch_mr_handler.get_branches_ready_for_archiving(mock_gl, config)

        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]['branch_name'], 'old-feature')
        self.assertEqual(len(mrs), 0)


class TestPerformAutomaticArchiving(unittest.TestCase):
    """Tests for perform_automatic_archiving function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'get_branches_ready_for_archiving')
    @patch.object(stale_branch_mr_handler, 'archive_stale_mr')
    @patch.object(stale_branch_mr_handler, 'archive_stale_branch')
    def test_performs_archiving_for_mrs(self, mock_archive_branch, mock_archive_mr, mock_get_ready, mock_gl):
        """Test that archiving is performed for MRs."""
        mock_gl.return_value = MagicMock()
        mock_get_ready.return_value = (
            [],  # No branches
            [{'iid': 42, 'branch_name': 'feature', 'project_id': 123, 'project_name': 'Test'}]
        )
        mock_archive_mr.return_value = {
            'success': True,
            'archived': True,
            'mr_closed': True,
            'deleted': True,
            'archive_path': '/path/to/archive.tar.gz',
            'error': None
        }

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'projects': [123],
            'stale_days': 30,
            'cleanup_weeks': 4,
            'archive_folder': self.temp_dir,
        }

        result = stale_branch_mr_handler.perform_automatic_archiving(config, dry_run=False)

        self.assertEqual(result['mrs_archived'], 1)
        self.assertEqual(result['mrs_failed'], 0)
        self.assertEqual(len(result['archived_items']), 1)
        mock_archive_mr.assert_called_once()

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'get_branches_ready_for_archiving')
    @patch.object(stale_branch_mr_handler, 'archive_stale_mr')
    @patch.object(stale_branch_mr_handler, 'archive_stale_branch')
    def test_performs_archiving_for_branches(self, mock_archive_branch, mock_archive_mr, mock_get_ready, mock_gl):
        """Test that archiving is performed for branches."""
        mock_gl.return_value = MagicMock()
        mock_get_ready.return_value = (
            [{'branch_name': 'orphan', 'project_id': 123, 'project_name': 'Test'}],
            []  # No MRs
        )
        mock_archive_branch.return_value = {
            'success': True,
            'archived': True,
            'deleted': True,
            'archive_path': '/path/to/archive.tar.gz',
            'error': None
        }

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'projects': [123],
            'stale_days': 30,
            'cleanup_weeks': 4,
            'archive_folder': self.temp_dir,
        }

        result = stale_branch_mr_handler.perform_automatic_archiving(config, dry_run=False)

        self.assertEqual(result['branches_archived'], 1)
        self.assertEqual(result['branches_failed'], 0)
        self.assertEqual(len(result['archived_items']), 1)
        mock_archive_branch.assert_called_once()

    @patch.object(stale_branch_mr_handler, 'create_gitlab_client')
    @patch.object(stale_branch_mr_handler, 'get_branches_ready_for_archiving')
    def test_returns_empty_summary_when_nothing_to_archive(self, mock_get_ready, mock_gl):
        """Test that empty summary is returned when nothing to archive."""
        mock_gl.return_value = MagicMock()
        mock_get_ready.return_value = ([], [])  # Nothing to archive

        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'projects': [123],
            'stale_days': 30,
            'cleanup_weeks': 4,
            'archive_folder': self.temp_dir,
        }

        result = stale_branch_mr_handler.perform_automatic_archiving(config, dry_run=False)

        self.assertEqual(result['branches_archived'], 0)
        self.assertEqual(result['mrs_archived'], 0)
        self.assertEqual(len(result['archived_items']), 0)


if __name__ == '__main__':
    unittest.main()
