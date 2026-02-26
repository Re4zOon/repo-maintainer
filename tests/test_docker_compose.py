"""Tests for Docker Compose configuration."""

import os
import unittest

import yaml


class TestDockerComposeConfig(unittest.TestCase):
    """Validate required Docker Compose volume mappings."""

    def test_archive_folder_volume_mounted_for_services(self):
        """Archive folder should be mounted for both services."""
        compose_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'docker-compose.yml'
        )
        with open(compose_path) as f:
            compose = yaml.safe_load(f)

        expected_volume = './archived_branches:/app/archived_branches'
        services = compose['services']
        self.assertIn(expected_volume, services['repo-maintainer']['volumes'])
        self.assertIn(expected_volume, services['repo-maintainer-webui']['volumes'])
