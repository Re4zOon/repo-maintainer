"""Tests for the WebUI module."""

import base64
import json
import os
import shutil
import tempfile
import unittest

import yaml

import stale_branch_mr_handler
from webui.app import create_app


class TestWebUIApp(unittest.TestCase):
    """Tests for the Flask application."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'config.yaml')
        self.db_path = os.path.join(self.temp_dir, 'test.db')

        # Create a test config
        self.test_config = {
            'gitlab': {
                'url': 'https://gitlab.example.com',
                'private_token': 'test-token'
            },
            'smtp': {
                'host': 'smtp.example.com',
                'port': 587,
                'from_email': 'test@example.com',
                'password': 'smtp-password'
            },
            'projects': [123, 456],
            'stale_days': 30,
            'cleanup_weeks': 4,
            'fallback_email': 'fallback@example.com',
            'database_path': self.db_path,
            'enable_auto_archive': False,
            'enable_mr_comments': True
        }

        with open(self.config_path, 'w') as f:
            yaml.safe_dump(self.test_config, f)

        # Initialize the database
        stale_branch_mr_handler.init_database(self.db_path)

        # Create the app with test config
        self.app = create_app(config_path=self.config_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Auth header for protected routes
        credentials = base64.b64encode(b'admin:admin').decode('utf-8')
        self.auth_header = {'Authorization': f'Basic {credentials}'}

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_health_check_no_auth_required(self):
        """Test that health check doesn't require authentication."""
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'healthy')
        self.assertIn('timestamp', data)
        self.assertIn('version', data)

    def test_dashboard_requires_auth(self):
        """Test that dashboard requires authentication."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 401)

    def test_dashboard_with_auth(self):
        """Test that dashboard works with authentication."""
        response = self.client.get('/', headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data)

    def test_config_page_requires_auth(self):
        """Test that config page requires authentication."""
        response = self.client.get('/config')
        self.assertEqual(response.status_code, 401)

    def test_config_page_with_auth(self):
        """Test that config page works with authentication."""
        response = self.client.get('/config', headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Configuration', response.data)

    def test_get_stats(self):
        """Test getting statistics."""
        response = self.client.get('/api/stats', headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)

        self.assertIn('notifications', data)
        self.assertIn('mr_comments', data)
        self.assertIn('config', data)

        # Check notification stats structure
        self.assertIn('total', data['notifications'])
        self.assertIn('branches', data['notifications'])
        self.assertIn('merge_requests', data['notifications'])
        self.assertIn('recent', data['notifications'])

        # Check config summary
        self.assertEqual(data['config']['stale_days'], 30)
        self.assertEqual(data['config']['projects_count'], 2)

    def test_get_config_sanitized(self):
        """Test that config endpoint returns sanitized data."""
        response = self.client.get('/api/config', headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)

        # Check that sensitive data is not exposed
        self.assertIn('gitlab', data)
        self.assertNotIn('private_token', data['gitlab'])
        self.assertTrue(data['gitlab']['has_token'])

        self.assertIn('smtp', data)
        self.assertNotIn('password', data['smtp'])
        self.assertTrue(data['smtp']['has_password'])

        # Check non-sensitive data is present
        self.assertEqual(data['stale_days'], 30)
        self.assertEqual(data['projects'], [123, 456])

    def test_update_config_valid(self):
        """Test updating configuration with valid data."""
        updates = {
            'stale_days': 45,
            'cleanup_weeks': 6,
            'enable_auto_archive': True
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['changes']['stale_days'], 45)
        self.assertEqual(data['changes']['cleanup_weeks'], 6)
        self.assertEqual(data['changes']['enable_auto_archive'], True)

        # Verify the file was updated
        with open(self.config_path, 'r') as f:
            saved_config = yaml.safe_load(f)
        self.assertEqual(saved_config['stale_days'], 45)

    def test_update_config_invalid_type(self):
        """Test updating configuration with invalid data type."""
        updates = {
            'stale_days': 'not a number'
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)

    def test_update_config_negative_value(self):
        """Test updating configuration with negative value."""
        updates = {
            'stale_days': -5
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)

    def test_update_config_projects(self):
        """Test updating project list."""
        updates = {
            'projects': [111, 222, 333]
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 200)

        # Verify
        response = self.client.get('/api/config', headers=self.auth_header)
        data = json.loads(response.data)
        self.assertEqual(data['projects'], [111, 222, 333])

    def test_update_config_invalid_projects(self):
        """Test updating with invalid project IDs."""
        updates = {
            'projects': [123, 'not-an-int', 456]
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)

    def test_update_config_empty_projects(self):
        """Test updating projects with an empty list."""
        updates = {
            'projects': []
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 200)

        # Verify
        response = self.client.get('/api/config', headers=self.auth_header)
        data = json.loads(response.data)
        self.assertEqual(data['projects'], [])

    def test_update_config_valid_fallback_email(self):
        """Test updating fallback_email with a valid email."""
        updates = {
            'fallback_email': 'valid@example.com'
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['changes']['fallback_email'], 'valid@example.com')

    def test_update_config_invalid_fallback_email(self):
        """Test updating fallback_email with an invalid email format."""
        updates = {
            'fallback_email': 'not-an-email'
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
        self.assertIn('email', data['error'].lower())

    def test_update_config_empty_fallback_email(self):
        """Test updating fallback_email with an empty string (to clear it)."""
        updates = {
            'fallback_email': ''
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 200)

    def test_update_config_archive_folder_path_traversal(self):
        """Test that archive_folder rejects path traversal."""
        updates = {
            'archive_folder': '../../../etc/passwd'
        }

        response = self.client.put(
            '/api/config',
            headers={**self.auth_header, 'Content-Type': 'application/json'},
            data=json.dumps(updates)
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
        self.assertIn('path traversal', data['error'].lower())

    def test_update_config_requires_json(self):
        """Test that config update requires JSON content type."""
        response = self.client.put(
            '/api/config',
            headers=self.auth_header,
            data='not json'
        )

        self.assertEqual(response.status_code, 400)

    def test_wrong_credentials(self):
        """Test that wrong credentials are rejected."""
        bad_credentials = base64.b64encode(b'wrong:wrong').decode('utf-8')
        bad_header = {'Authorization': f'Basic {bad_credentials}'}

        response = self.client.get('/', headers=bad_header)
        self.assertEqual(response.status_code, 401)

    def test_stats_with_data(self):
        """Test stats endpoint with actual notification data."""
        # Add some notification records
        from datetime import datetime, timezone
        stale_branch_mr_handler.record_notification(
            self.db_path, 'user1@example.com', 'branch', 123, 'feature-1'
        )
        stale_branch_mr_handler.record_notification(
            self.db_path, 'user2@example.com', 'merge_request', 456, 42
        )
        stale_branch_mr_handler.record_mr_comment(
            self.db_path, 123, 10, 0
        )

        response = self.client.get('/api/stats', headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)

        self.assertEqual(data['notifications']['total'], 2)
        self.assertEqual(data['notifications']['branches'], 1)
        self.assertEqual(data['notifications']['merge_requests'], 1)
        self.assertEqual(len(data['notifications']['recent']), 2)

        self.assertEqual(data['mr_comments']['total'], 1)
        self.assertEqual(len(data['mr_comments']['recent']), 1)


class TestWebUIAppWithMissingConfig(unittest.TestCase):
    """Tests for the Flask application with missing config."""

    def test_app_handles_missing_config(self):
        """Test that app handles missing config file gracefully."""
        app = create_app(config_path='/nonexistent/config.yaml')
        app.config['TESTING'] = True
        client = app.test_client()

        # Health check should still work
        response = client.get('/api/health')
        self.assertEqual(response.status_code, 200)

        # Authenticated routes should return empty/default config
        credentials = base64.b64encode(b'admin:admin').decode('utf-8')
        auth_header = {'Authorization': f'Basic {credentials}'}

        response = client.get('/api/config', headers=auth_header)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        # Should have defaults
        self.assertEqual(data['stale_days'], 30)


if __name__ == '__main__':
    unittest.main()
