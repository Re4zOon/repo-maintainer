#!/usr/bin/env python3
"""
Flask-based WebUI for the repo-maintainer tool.

This module provides a web interface for:
- Viewing statistics and dashboard information
- Managing configuration
- Monitoring system health
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

import yaml
from flask import Flask, jsonify, render_template, request

# Import from the main module for shared functionality
import stale_branch_mr_handler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app(config_path=None, test_config=None):
    """
    Create and configure the Flask application.

    Args:
        config_path: Path to the YAML configuration file
        test_config: Optional test configuration dictionary

    Returns:
        Configured Flask application
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )

    # Default configuration
    app.config['SECRET_KEY'] = os.environ.get('WEBUI_SECRET_KEY', 'change-me-in-production')
    app.config['WEBUI_USERNAME'] = os.environ.get('WEBUI_USERNAME', 'admin')
    app.config['WEBUI_PASSWORD'] = os.environ.get('WEBUI_PASSWORD', 'admin')

    if test_config:
        app.config.update(test_config)
    else:
        # Load the main application config
        config_path = config_path or os.environ.get('CONFIG_PATH', 'config.yaml')
        app.config['CONFIG_PATH'] = config_path
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    main_config = yaml.safe_load(f)
                app.config['MAIN_CONFIG'] = main_config
            else:
                logger.warning(f"Configuration file not found: {config_path}")
                app.config['MAIN_CONFIG'] = {}
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            app.config['MAIN_CONFIG'] = {}

    # Register routes
    register_routes(app)

    return app


def check_auth(username, password):
    """Check if a username/password combination is valid."""
    return (username == os.environ.get('WEBUI_USERNAME', 'admin') and
            password == os.environ.get('WEBUI_PASSWORD', 'admin'))


def authenticate():
    """Send a 401 response that enables basic auth."""
    return jsonify({
        'error': 'Authentication required',
        'message': 'Please provide valid credentials'
    }), 401, {'WWW-Authenticate': 'Basic realm="repo-maintainer"'}


def requires_auth(f):
    """Decorator to require HTTP basic authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def register_routes(app):
    """Register all routes for the application."""

    @app.route('/')
    @requires_auth
    def index():
        """Render the main dashboard."""
        return render_template('dashboard.html')

    @app.route('/config')
    @requires_auth
    def config_page():
        """Render the configuration page."""
        return render_template('config.html')

    @app.route('/api/health')
    def health_check():
        """Health check endpoint."""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0'
        })

    @app.route('/api/stats')
    @requires_auth
    def get_stats():
        """Get statistics from the notification database."""
        config = app.config.get('MAIN_CONFIG', {})
        db_path = config.get('database_path', stale_branch_mr_handler.DEFAULT_DATABASE_PATH)

        stats = {
            'notifications': {
                'total': 0,
                'branches': 0,
                'merge_requests': 0,
                'recent': []
            },
            'mr_comments': {
                'total': 0,
                'recent': []
            },
            'config': {
                'stale_days': config.get('stale_days', 30),
                'cleanup_weeks': config.get('cleanup_weeks', 4),
                'notification_frequency_days': config.get(
                    'notification_frequency_days',
                    stale_branch_mr_handler.DEFAULT_NOTIFICATION_FREQUENCY_DAYS
                ),
                'enable_auto_archive': config.get(
                    'enable_auto_archive',
                    stale_branch_mr_handler.DEFAULT_ENABLE_AUTO_ARCHIVE
                ),
                'enable_mr_comments': config.get(
                    'enable_mr_comments',
                    stale_branch_mr_handler.DEFAULT_ENABLE_MR_COMMENTS
                ),
                'projects_count': len(config.get('projects', []))
            }
        }

        try:
            if os.path.exists(db_path):
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()

                    # Get notification counts
                    cursor.execute(
                        "SELECT COUNT(*) FROM notification_history WHERE item_type = 'branch'"
                    )
                    stats['notifications']['branches'] = cursor.fetchone()[0]

                    cursor.execute(
                        "SELECT COUNT(*) FROM notification_history WHERE item_type = 'merge_request'"
                    )
                    stats['notifications']['merge_requests'] = cursor.fetchone()[0]

                    stats['notifications']['total'] = (
                        stats['notifications']['branches'] +
                        stats['notifications']['merge_requests']
                    )

                    # Get recent notifications
                    cursor.execute('''
                        SELECT recipient_email, item_type, project_id, item_key, last_notified_at
                        FROM notification_history
                        ORDER BY last_notified_at DESC
                        LIMIT 10
                    ''')
                    recent = cursor.fetchall()
                    stats['notifications']['recent'] = [
                        {
                            'recipient': row[0],
                            'type': row[1],
                            'project_id': row[2],
                            'item': row[3],
                            'notified_at': row[4]
                        }
                        for row in recent
                    ]

                    # Get MR comment counts
                    cursor.execute("SELECT COUNT(*) FROM mr_comment_history")
                    stats['mr_comments']['total'] = cursor.fetchone()[0]

                    # Get recent MR comments
                    cursor.execute('''
                        SELECT project_id, mr_iid, comment_index, last_commented_at
                        FROM mr_comment_history
                        ORDER BY last_commented_at DESC
                        LIMIT 10
                    ''')
                    recent_comments = cursor.fetchall()
                    stats['mr_comments']['recent'] = [
                        {
                            'project_id': row[0],
                            'mr_iid': row[1],
                            'comment_index': row[2],
                            'commented_at': row[3]
                        }
                        for row in recent_comments
                    ]

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            stats['error'] = f"Database error: {str(e)}"

        return jsonify(stats)

    @app.route('/api/config', methods=['GET'])
    @requires_auth
    def get_config():
        """Get the current configuration (sanitized)."""
        config = app.config.get('MAIN_CONFIG', {})

        # Return sanitized config (no sensitive data)
        safe_config = {
            'gitlab': {
                'url': config.get('gitlab', {}).get('url', ''),
                'has_token': bool(config.get('gitlab', {}).get('private_token'))
            },
            'smtp': {
                'host': config.get('smtp', {}).get('host', ''),
                'port': config.get('smtp', {}).get('port', 587),
                'use_tls': config.get('smtp', {}).get('use_tls', True),
                'from_email': config.get('smtp', {}).get('from_email', ''),
                'has_password': bool(config.get('smtp', {}).get('password'))
            },
            'projects': config.get('projects', []),
            'stale_days': config.get('stale_days', 30),
            'cleanup_weeks': config.get('cleanup_weeks', 4),
            'notification_frequency_days': config.get(
                'notification_frequency_days',
                stale_branch_mr_handler.DEFAULT_NOTIFICATION_FREQUENCY_DAYS
            ),
            'fallback_email': config.get('fallback_email', ''),
            'database_path': config.get(
                'database_path',
                stale_branch_mr_handler.DEFAULT_DATABASE_PATH
            ),
            'enable_auto_archive': config.get(
                'enable_auto_archive',
                stale_branch_mr_handler.DEFAULT_ENABLE_AUTO_ARCHIVE
            ),
            'archive_folder': config.get(
                'archive_folder',
                stale_branch_mr_handler.DEFAULT_ARCHIVE_FOLDER
            ),
            'enable_mr_comments': config.get(
                'enable_mr_comments',
                stale_branch_mr_handler.DEFAULT_ENABLE_MR_COMMENTS
            ),
            'mr_comment_inactivity_days': config.get(
                'mr_comment_inactivity_days',
                stale_branch_mr_handler.DEFAULT_MR_COMMENT_INACTIVITY_DAYS
            ),
            'mr_comment_frequency_days': config.get(
                'mr_comment_frequency_days',
                stale_branch_mr_handler.DEFAULT_MR_COMMENT_FREQUENCY_DAYS
            )
        }

        return jsonify(safe_config)

    @app.route('/api/config', methods=['PUT'])
    @requires_auth
    def update_config():
        """Update non-sensitive configuration values."""
        config_path = app.config.get('CONFIG_PATH', 'config.yaml')
        current_config = app.config.get('MAIN_CONFIG', {})

        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400

        updates = request.get_json()

        # List of allowed fields to update (non-sensitive)
        allowed_fields = [
            'stale_days',
            'cleanup_weeks',
            'notification_frequency_days',
            'fallback_email',
            'enable_auto_archive',
            'archive_folder',
            'enable_mr_comments',
            'mr_comment_inactivity_days',
            'mr_comment_frequency_days',
            'projects'
        ]

        # Validate and apply updates
        changes = {}
        for field in allowed_fields:
            if field in updates:
                new_value = updates[field]

                # Type validation
                if field in ['stale_days', 'cleanup_weeks', 'notification_frequency_days',
                             'mr_comment_inactivity_days', 'mr_comment_frequency_days']:
                    if not isinstance(new_value, int) or new_value < 1:
                        return jsonify({
                            'error': f'{field} must be a positive integer'
                        }), 400

                if field in ['enable_auto_archive', 'enable_mr_comments']:
                    if not isinstance(new_value, bool):
                        return jsonify({
                            'error': f'{field} must be a boolean'
                        }), 400

                if field == 'projects':
                    if not isinstance(new_value, list):
                        return jsonify({
                            'error': 'projects must be a list'
                        }), 400
                    # Validate all items are integers
                    for item in new_value:
                        if not isinstance(item, int):
                            return jsonify({
                                'error': 'All project IDs must be integers'
                            }), 400

                changes[field] = new_value
                current_config[field] = new_value

        if not changes:
            return jsonify({'message': 'No changes to apply', 'changes': {}}), 200

        # Save to file
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(current_config, f, default_flow_style=False)

            app.config['MAIN_CONFIG'] = current_config

            return jsonify({
                'message': 'Configuration updated successfully',
                'changes': changes
            })

        except IOError as e:
            logger.error(f"Error saving configuration: {e}")
            return jsonify({
                'error': f'Failed to save configuration: {str(e)}'
            }), 500

    @app.route('/api/config/history')
    @requires_auth
    def get_config_history():
        """
        Get configuration change history.
        Note: This is a placeholder - actual implementation would need
        a config change tracking mechanism.
        """
        return jsonify({
            'message': 'Config history not yet implemented',
            'history': []
        })


def main():
    """Run the WebUI server."""
    import argparse

    parser = argparse.ArgumentParser(description='Run the repo-maintainer WebUI')
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=int(os.environ.get('WEBUI_PORT', 5000)),
        help='Port to run the server on (default: 5000)'
    )
    parser.add_argument(
        '-H', '--host',
        default=os.environ.get('WEBUI_HOST', '0.0.0.0'),
        help='Host to bind the server to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Run in debug mode'
    )

    args = parser.parse_args()

    app = create_app(config_path=args.config)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
