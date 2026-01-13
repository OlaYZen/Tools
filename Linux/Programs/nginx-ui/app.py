from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nginx_ui.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

db = SQLAlchemy(app)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class FileEdit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # read, write, delete
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=True)
    
    user = db.relationship('User', backref=db.backref('edits', lazy=True))

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    failed_attempts = db.Column(db.Integer, default=0)
    last_attempt = db.Column(db.DateTime, default=datetime.utcnow)
    locked_until = db.Column(db.DateTime, nullable=True)

# Helper functions for login rate limiting
def get_lockout_duration(failed_attempts):
    """Calculate lockout duration based on failed attempts"""
    if failed_attempts >= 9:
        return 30  # 30 minutes max
    elif failed_attempts >= 6:
        return 10  # 10 minutes
    elif failed_attempts >= 3:
        return 5   # 5 minutes
    return 0

def check_login_lockout(username):
    """Check if user is currently locked out"""
    attempt = LoginAttempt.query.filter_by(username=username).first()
    
    if not attempt:
        return None, 0
    
    # Check if locked and still within lockout period
    if attempt.locked_until and attempt.locked_until > datetime.utcnow():
        remaining_seconds = int((attempt.locked_until - datetime.utcnow()).total_seconds())
        return remaining_seconds, attempt.failed_attempts
    
    return None, attempt.failed_attempts

def record_failed_login(username):
    """Record a failed login attempt and apply lockout if needed"""
    attempt = LoginAttempt.query.filter_by(username=username).first()
    
    if not attempt:
        attempt = LoginAttempt(username=username, failed_attempts=1, last_attempt=datetime.utcnow())
        db.session.add(attempt)
    else:
        attempt.failed_attempts += 1
        attempt.last_attempt = datetime.utcnow()
    
    # Calculate lockout duration
    lockout_minutes = get_lockout_duration(attempt.failed_attempts)
    if lockout_minutes > 0:
        attempt.locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)
    
    db.session.commit()
    return attempt.failed_attempts, lockout_minutes

def clear_failed_logins(username):
    """Clear failed login attempts on successful login"""
    attempt = LoginAttempt.query.filter_by(username=username).first()
    if attempt:
        db.session.delete(attempt)
        db.session.commit()

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        # If already logged in, redirect to index
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html')
    
    data = request.get_json() if request.is_json else request.form
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    # Check if user is locked out
    lockout_seconds, failed_count = check_login_lockout(username)
    if lockout_seconds:
        minutes = lockout_seconds // 60
        seconds = lockout_seconds % 60
        if minutes > 0:
            time_msg = f"{minutes} minute{'s' if minutes != 1 else ''} and {seconds} second{'s' if seconds != 1 else ''}"
        else:
            time_msg = f"{seconds} second{'s' if seconds != 1 else ''}"
        return jsonify({
            'error': f'Account temporarily locked due to multiple failed login attempts. Please try again in {time_msg}.',
            'locked': True,
            'retry_after': lockout_seconds
        }), 429
    
    user = User.query.filter_by(username=username).first()
    
    if user and user.is_active and user.check_password(password):
        # Clear any failed login attempts
        clear_failed_logins(username)
        
        session['user_id'] = user.id
        session['username'] = user.username
        session['must_change_password'] = user.must_change_password
        session.permanent = True
        return jsonify({
            'success': True, 
            'message': 'Login successful',
            'must_change_password': user.must_change_password
        })
    
    # Record failed login attempt
    failed_count, lockout_minutes = record_failed_login(username)
    
    error_msg = 'Invalid credentials'
    if lockout_minutes > 0:
        error_msg = f'Invalid credentials. Account locked for {lockout_minutes} minutes due to multiple failed attempts.'
    elif failed_count > 0:
        remaining = 3 - (failed_count % 3)
        if remaining > 0:
            error_msg = f'Invalid credentials. {remaining} attempt{"s" if remaining != 1 else ""} remaining before temporary lockout.'
    
    return jsonify({'error': error_msg}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Current and new password are required'}), 400
    
    if len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters long'}), 400
    
    user = User.query.get(session['user_id'])
    
    if not user or not user.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    # Update password
    user.set_password(new_password)
    user.must_change_password = False
    db.session.commit()
    
    # Update session
    session['must_change_password'] = False
    
    return jsonify({'success': True, 'message': 'Password changed successfully'})

@app.route('/api/files/list', methods=['POST'])
@login_required
def list_files():
    data = request.get_json()
    path = data.get('path', '/')
    
    # Get nginx config directory from settings or use default
    nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
    
    # Resolve the full path
    if path.startswith('/'):
        full_path = os.path.join(nginx_dir, path.lstrip('/'))
    else:
        full_path = os.path.join(nginx_dir, path)
    
    # Security: Ensure path is within nginx directory
    full_path = os.path.abspath(full_path)
    nginx_dir = os.path.abspath(nginx_dir)
    
    if not full_path.startswith(nginx_dir):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(full_path):
        return jsonify({'error': 'Path not found'}), 404
    
    if not os.path.isdir(full_path):
        return jsonify({'error': 'Not a directory'}), 400
    
    try:
        items = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            relative_path = os.path.relpath(item_path, nginx_dir)
            
            stat_info = os.stat(item_path)
            items.append({
                'name': item,
                'path': '/' + relative_path,
                'type': 'directory' if os.path.isdir(item_path) else 'file',
                'size': stat_info.st_size if os.path.isfile(item_path) else 0,
                'modified': datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                'permissions': oct(stat_info.st_mode)[-3:]
            })
        
        # Sort: directories first, then files
        items.sort(key=lambda x: (x['type'] != 'directory', x['name'].lower()))
        
        log_file_action('read', full_path, True)
        return jsonify({'items': items, 'current_path': '/' + os.path.relpath(full_path, nginx_dir)})
    
    except PermissionError:
        log_file_action('read', full_path, False)
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        log_file_action('read', full_path, False)
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/read', methods=['POST'])
@login_required
def read_file():
    data = request.get_json()
    path = data.get('path')
    
    if not path:
        return jsonify({'error': 'Path required'}), 400
    
    nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
    full_path = os.path.join(nginx_dir, path.lstrip('/'))
    full_path = os.path.abspath(full_path)
    nginx_dir = os.path.abspath(nginx_dir)
    
    if not full_path.startswith(nginx_dir):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(full_path):
        return jsonify({'error': 'File not found'}), 404
    
    if not os.path.isfile(full_path):
        return jsonify({'error': 'Not a file'}), 400
    
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        
        log_file_action('read', full_path, True)
        return jsonify({
            'content': content,
            'path': path,
            'name': os.path.basename(full_path)
        })
    
    except PermissionError:
        log_file_action('read', full_path, False)
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        log_file_action('read', full_path, False)
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/write', methods=['POST'])
@login_required
def write_file():
    data = request.get_json()
    path = data.get('path')
    content = data.get('content', '')
    
    if not path:
        return jsonify({'error': 'Path required'}), 400
    
    nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
    full_path = os.path.join(nginx_dir, path.lstrip('/'))
    full_path = os.path.abspath(full_path)
    nginx_dir = os.path.abspath(nginx_dir)
    
    if not full_path.startswith(nginx_dir):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Create backup before writing
        if os.path.exists(full_path):
            backup_path = full_path + '.backup'
            with open(full_path, 'r') as src:
                with open(backup_path, 'w') as dst:
                    dst.write(src.read())
        
        # Write new content
        with open(full_path, 'w') as f:
            f.write(content)
        
        log_file_action('write', full_path, True)
        
        # Reload nginx after successful file write
        reload_success, reload_message = reload_nginx()
        if reload_success:
            return jsonify({'success': True, 'message': 'File saved successfully and nginx reloaded'})
        else:
            return jsonify({'success': True, 'message': f'File saved successfully, but nginx reload failed: {reload_message}'})
    
    except PermissionError:
        log_file_action('write', full_path, False)
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        log_file_action('write', full_path, False)
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/create', methods=['POST'])
@login_required
def create_file():
    data = request.get_json()
    path = data.get('path')
    file_type = data.get('type', 'file')  # 'file' or 'directory'
    
    if not path:
        return jsonify({'error': 'Path required'}), 400
    
    nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
    full_path = os.path.join(nginx_dir, path.lstrip('/'))
    full_path = os.path.abspath(full_path)
    nginx_dir = os.path.abspath(nginx_dir)
    
    if not full_path.startswith(nginx_dir):
        return jsonify({'error': 'Access denied'}), 403
    
    if os.path.exists(full_path):
        return jsonify({'error': 'Path already exists'}), 400
    
    try:
        if file_type == 'directory':
            os.makedirs(full_path)
        else:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write('')
        
        log_file_action('create', full_path, True)
        return jsonify({'success': True, 'message': f'{file_type.capitalize()} created successfully'})
    
    except PermissionError:
        log_file_action('create', full_path, False)
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        log_file_action('create', full_path, False)
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/delete', methods=['POST'])
@login_required
def delete_file():
    data = request.get_json()
    path = data.get('path')
    
    if not path:
        return jsonify({'error': 'Path required'}), 400
    
    nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
    full_path = os.path.join(nginx_dir, path.lstrip('/'))
    full_path = os.path.abspath(full_path)
    nginx_dir = os.path.abspath(nginx_dir)
    
    if not full_path.startswith(nginx_dir):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(full_path):
        return jsonify({'error': 'Path not found'}), 404
    
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            import shutil
            shutil.rmtree(full_path)
        
        log_file_action('delete', full_path, True)
        return jsonify({'success': True, 'message': 'Deleted successfully'})
    
    except PermissionError:
        log_file_action('delete', full_path, False)
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        log_file_action('delete', full_path, False)
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'GET':
        nginx_dir = get_config_value('nginx_dir', '/etc/nginx')
        docker_enabled = get_config_value('docker_enabled', 'false').lower() == 'true'
        docker_container_name = get_config_value('docker_container_name', '')
        user = User.query.get(session['user_id'])
        return jsonify({
            'nginx_dir': nginx_dir,
            'docker_enabled': docker_enabled,
            'docker_container_name': docker_container_name,
            'username': user.username if user else ''
        })
    else:
        data = request.get_json()
        nginx_dir = data.get('nginx_dir')
        docker_enabled = data.get('docker_enabled')
        docker_container_name = data.get('docker_container_name')
        new_username = data.get('username')
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        updates_made = []
        password_changed = False
        
        # Handle nginx directory update
        if nginx_dir:
            if not os.path.isdir(nginx_dir):
                return jsonify({'error': 'Invalid nginx directory'}), 400
            set_config_value('nginx_dir', nginx_dir)
            updates_made.append('directory')
        
        # Handle Docker settings
        if docker_enabled is not None:
            set_config_value('docker_enabled', str(docker_enabled).lower())
            updates_made.append('docker_enabled')
        
        if docker_container_name is not None:
            set_config_value('docker_container_name', docker_container_name)
            updates_made.append('docker_container_name')
        
        # Handle username change
        if new_username and new_username != user.username:
            # Validate username
            if len(new_username) < 3:
                return jsonify({'error': 'Username must be at least 3 characters long'}), 400
            
            # Check if username already exists
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                return jsonify({'error': 'Username already taken'}), 400
            
            user.username = new_username
            session['username'] = new_username
            updates_made.append('username')
        
        # Handle password change
        if current_password and new_password:
            # Verify current password
            if not user.check_password(current_password):
                return jsonify({'error': 'Current password is incorrect'}), 401
            
            # Validate new password
            if len(new_password) < 8:
                return jsonify({'error': 'New password must be at least 8 characters long'}), 400
            
            user.set_password(new_password)
            password_changed = True
            updates_made.append('password')
        
        # Save changes to database
        if updates_made:
            db.session.commit()
            
            message = 'Settings updated: ' + ', '.join(updates_made)
            return jsonify({
                'success': True,
                'message': message,
                'username': user.username,
                'password_changed': password_changed
            })
        
        return jsonify({'success': True, 'message': 'No changes made'})

@app.route('/api/activity', methods=['GET'])
@login_required
def activity():
    limit = request.args.get('limit', 50, type=int)
    edits = FileEdit.query.order_by(FileEdit.timestamp.desc()).limit(limit).all()
    
    return jsonify({
        'activities': [{
            'id': edit.id,
            'username': edit.user.username,
            'file_path': edit.file_path,
            'action': edit.action,
            'timestamp': edit.timestamp.isoformat(),
            'success': edit.success
        } for edit in edits]
    })

# Helper functions
def log_file_action(action, file_path, success):
    try:
        edit = FileEdit(
            user_id=session.get('user_id'),
            file_path=file_path,
            action=action,
            success=success
        )
        db.session.add(edit)
        db.session.commit()
    except:
        db.session.rollback()

def get_config_value(key, default=None):
    config = Config.query.filter_by(key=key).first()
    return config.value if config else default

def set_config_value(key, value):
    config = Config.query.filter_by(key=key).first()
    if config:
        config.value = value
        config.updated_at = datetime.utcnow()
    else:
        config = Config(key=key, value=value)
        db.session.add(config)
    db.session.commit()

def reload_nginx():
    """Reload nginx configuration using Docker or direct command based on settings"""
    import subprocess
    
    docker_enabled = get_config_value('docker_enabled', 'false').lower() == 'true'
    docker_container_name = get_config_value('docker_container_name', '')
    
    try:
        if docker_enabled and docker_container_name:
            # Use Docker to reload nginx
            cmd = ['docker', 'exec', docker_container_name, 'nginx', '-s', 'reload']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        else:
            # Use direct nginx command
            cmd = ['nginx', '-s', 'reload']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return True, "Nginx reloaded successfully"
        else:
            return False, f"Nginx reload failed: {result.stderr}"
    
    except subprocess.TimeoutExpired:
        return False, "Nginx reload timed out"
    except FileNotFoundError:
        if docker_enabled:
            return False, f"Docker command not found or container '{docker_container_name}' not accessible"
        else:
            return False, "Nginx command not found"
    except Exception as e:
        return False, f"Error reloading nginx: {str(e)}"

# Initialize database and create default user
def init_db():
    with app.app_context():
        db.create_all()
        
        # Migrate existing users to have must_change_password field
        try:
            # Check if any users have NULL must_change_password (new column)
            users_to_update = User.query.filter(User.must_change_password == None).all()
            for user in users_to_update:
                # If user still has default password, require change
                if user.username == 'admin' and user.check_password('admin'):
                    user.must_change_password = True
                else:
                    user.must_change_password = False
            if users_to_update:
                db.session.commit()
                print(f'Migrated {len(users_to_update)} existing user(s)')
        except Exception as e:
            print(f'Migration note: {e}')
        
        # Create default admin user if no users exist
        if User.query.count() == 0:
            admin = User(username='admin', email='admin@localhost', must_change_password=True)
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
            print('Created default admin user (username: admin, password: admin)')
            print('IMPORTANT: You will be required to change the password on first login!')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=9000)