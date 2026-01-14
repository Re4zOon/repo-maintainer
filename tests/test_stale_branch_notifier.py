"""Tests for the GitLab Stale Branch Notifier."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import stale_branch_notifier
from stale_branch_notifier import ConfigurationError


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
        stale_branch_notifier.validate_config(config)

    def test_empty_config(self):
        """Test that empty config raises error."""
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_notifier.validate_config({})
        self.assertIn('empty', str(ctx.exception).lower())

    def test_missing_gitlab_section(self):
        """Test that missing gitlab section raises error."""
        config = {
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_notifier.validate_config(config)
        self.assertIn('gitlab', str(ctx.exception).lower())

    def test_missing_gitlab_url(self):
        """Test that missing gitlab url raises error."""
        config = {
            'gitlab': {'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_notifier.validate_config(config)
        self.assertIn('url', str(ctx.exception).lower())

    def test_missing_smtp_section(self):
        """Test that missing smtp section raises error."""
        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'projects': [1],
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_notifier.validate_config(config)
        self.assertIn('smtp', str(ctx.exception).lower())

    def test_missing_projects(self):
        """Test that missing projects raises error."""
        config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
        }
        with self.assertRaises(ConfigurationError) as ctx:
            stale_branch_notifier.validate_config(config)
        self.assertIn('projects', str(ctx.exception).lower())


class TestParseDateCommit(unittest.TestCase):
    """Tests for parse_commit_date function."""

    def test_parse_z_suffix(self):
        """Test parsing date with Z suffix."""
        result = stale_branch_notifier.parse_commit_date('2023-01-15T10:30:00Z')
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_parse_with_offset(self):
        """Test parsing date with timezone offset."""
        result = stale_branch_notifier.parse_commit_date('2023-01-15T10:30:00+02:00')
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.hour, 10)

    def test_parse_with_microseconds(self):
        """Test parsing date with microseconds."""
        result = stale_branch_notifier.parse_commit_date('2023-01-15T10:30:00.123456+00:00')
        self.assertEqual(result.year, 2023)

    def test_parse_invalid_format(self):
        """Test that invalid format raises ValueError."""
        with self.assertRaises(ValueError):
            stale_branch_notifier.parse_commit_date('not-a-date')


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config function."""

    @patch('builtins.open')
    @patch('yaml.safe_load')
    @patch.object(stale_branch_notifier, 'validate_config')
    def test_load_config_success(self, mock_validate, mock_yaml_load, mock_open):
        """Test successful config loading."""
        expected_config = {
            'gitlab': {'url': 'https://gitlab.example.com', 'private_token': 'token'},
            'smtp': {'host': 'smtp.example.com', 'port': 587, 'from_email': 'test@example.com'},
            'projects': [1],
        }
        mock_yaml_load.return_value = expected_config

        result = stale_branch_notifier.load_config('config.yaml')

        self.assertEqual(result, expected_config)
        mock_validate.assert_called_once_with(expected_config)

    def test_load_config_file_not_found(self):
        """Test config loading with missing file."""
        with self.assertRaises(FileNotFoundError):
            stale_branch_notifier.load_config('nonexistent.yaml')


class TestIsUserActive(unittest.TestCase):
    """Tests for is_user_active function."""

    def test_active_user(self):
        """Test that active user returns True."""
        mock_gl = MagicMock()
        mock_user = MagicMock()
        mock_user.state = 'active'
        mock_gl.users.list.return_value = [mock_user]

        result = stale_branch_notifier.is_user_active(mock_gl, 'user@example.com')

        self.assertTrue(result)
        mock_gl.users.list.assert_called_once_with(search='user@example.com', per_page=1)

    def test_inactive_user(self):
        """Test that inactive user returns False."""
        mock_gl = MagicMock()
        mock_user = MagicMock()
        mock_user.state = 'blocked'
        mock_gl.users.list.return_value = [mock_user]

        result = stale_branch_notifier.is_user_active(mock_gl, 'user@example.com')

        self.assertFalse(result)

    def test_user_not_found(self):
        """Test that non-existent user returns False."""
        mock_gl = MagicMock()
        mock_gl.users.list.return_value = []

        result = stale_branch_notifier.is_user_active(mock_gl, 'nonexistent@example.com')

        self.assertFalse(result)


class TestGetNotificationEmail(unittest.TestCase):
    """Tests for get_notification_email function."""

    @patch.object(stale_branch_notifier, 'is_user_active')
    def test_active_user_uses_own_email(self, mock_is_active):
        """Test that active user gets their own email."""
        mock_is_active.return_value = True
        mock_gl = MagicMock()

        result = stale_branch_notifier.get_notification_email(
            mock_gl, 'user@example.com', 'fallback@example.com'
        )

        self.assertEqual(result, 'user@example.com')

    @patch.object(stale_branch_notifier, 'is_user_active')
    def test_inactive_user_uses_fallback_email(self, mock_is_active):
        """Test that inactive user gets fallback email."""
        mock_is_active.return_value = False
        mock_gl = MagicMock()

        result = stale_branch_notifier.get_notification_email(
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

        result = stale_branch_notifier.get_stale_branches(mock_gl, 1, 30)

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

        result = stale_branch_notifier.get_stale_branches(mock_gl, 1, 30)

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

        result = stale_branch_notifier.get_stale_branches(mock_gl, 1, 30)

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

        result = stale_branch_notifier.generate_email_content(branches, 30, 4)

        self.assertIn('Test Project', result)
        self.assertIn('feature-branch', result)
        self.assertIn('Test User', result)
        self.assertIn('30 days', result)
        self.assertIn('4 weeks', result)

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

        result = stale_branch_notifier.generate_email_content(branches, 30, 4)

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

        result = stale_branch_notifier.send_email(
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

        result = stale_branch_notifier.send_email(
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

    @patch.object(stale_branch_notifier, 'get_stale_branches')
    @patch.object(stale_branch_notifier, 'get_notification_email')
    def test_groups_branches_by_email(self, mock_get_email, mock_get_branches):
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
        mock_get_email.side_effect = lambda gl, email, fallback: email

        config = {
            'stale_days': 30,
            'fallback_email': 'fallback@example.com',
            'projects': [1],
        }

        result = stale_branch_notifier.collect_stale_branches_by_email(mock_gl, config)

        self.assertEqual(len(result), 2)
        self.assertIn('user1@example.com', result)
        self.assertIn('user2@example.com', result)

    @patch.object(stale_branch_notifier, 'get_stale_branches')
    @patch.object(stale_branch_notifier, 'get_notification_email')
    def test_skips_branches_without_email_and_no_fallback(self, mock_get_email, mock_get_branches):
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
        # No fallback email configured
        mock_get_email.return_value = ''

        config = {
            'stale_days': 30,
            'fallback_email': '',  # No fallback
            'projects': [1],
        }

        result = stale_branch_notifier.collect_stale_branches_by_email(mock_gl, config)

        # Branch should be skipped
        self.assertEqual(len(result), 0)


if __name__ == '__main__':
    unittest.main()
