"""
Local User Manager - Linux System User Operations
Provides secure management of local Linux users on the server.

SECURITY WARNING: This module performs privileged operations.
Only use through authenticated API endpoints with proper authorization.
"""

import subprocess
import pwd
import grp
import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Security constants
MIN_UID = 1000  # Minimum UID for non-system users
VALID_USERNAME_PATTERN = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
VALID_SSH_KEY_PATTERN = re.compile(r'^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521) [A-Za-z0-9+/]+[=]{0,3}( .*)?$')

# System users to protect from operations (expanded list)
PROTECTED_USERS = {
    'root', 'daemon', 'bin', 'sys', 'sync', 'games', 'man', 'lp', 'mail',
    'news', 'uucp', 'proxy', 'www-data', 'backup', 'list', 'irc', 'gnats',
    'nobody', 'systemd-network', 'systemd-resolve', 'messagebus', 'systemd-timesync',
    'syslog', '_apt', 'tss', 'uuidd', 'tcpdump', 'landscape', 'fwupd-refresh',
    'pollinate', 'lxd', 'postgres', 'redis', 'docker', 'nginx', 'keycloak',
    'muut', 'ucadmin'  # Protect main admin users
}


class LocalUserError(Exception):
    """Base exception for local user operations"""
    pass


class ValidationError(LocalUserError):
    """Input validation failed"""
    pass


class SecurityError(LocalUserError):
    """Security policy violation"""
    pass


class SystemError(LocalUserError):
    """System command execution failed"""
    pass


def validate_username(username: str) -> None:
    """
    Validate username meets security requirements.

    Args:
        username: Username to validate

    Raises:
        ValidationError: If username is invalid
        SecurityError: If username is protected
    """
    if not username:
        raise ValidationError("Username cannot be empty")

    if len(username) > 32:
        raise ValidationError("Username too long (max 32 characters)")

    if not VALID_USERNAME_PATTERN.match(username):
        raise ValidationError(
            "Username must start with lowercase letter or underscore, "
            "followed by lowercase letters, digits, underscores or hyphens"
        )

    if username in PROTECTED_USERS:
        raise SecurityError(f"Cannot perform operations on protected user: {username}")

    # Check if user is a system user (UID < 1000)
    try:
        user_info = pwd.getpwnam(username)
        if user_info.pw_uid < MIN_UID:
            raise SecurityError(f"Cannot perform operations on system user: {username} (UID {user_info.pw_uid})")
    except KeyError:
        # User doesn't exist yet, which is fine for create operations
        pass


def validate_ssh_key(ssh_key: str) -> None:
    """
    Validate SSH public key format.

    Args:
        ssh_key: SSH public key to validate

    Raises:
        ValidationError: If key format is invalid
    """
    if not ssh_key:
        raise ValidationError("SSH key cannot be empty")

    key_stripped = ssh_key.strip()
    if not VALID_SSH_KEY_PATTERN.match(key_stripped):
        raise ValidationError(
            "Invalid SSH key format. Must be a valid public key "
            "(ssh-rsa, ssh-ed25519, or ecdsa-sha2-nistp*)"
        )


def run_command(cmd: List[str], input_data: Optional[str] = None) -> Tuple[int, str, str]:
    """
    Run a system command with security checks.

    Args:
        cmd: Command and arguments to execute
        input_data: Optional input to pipe to command

    Returns:
        Tuple of (return_code, stdout, stderr)

    Raises:
        ValidationError: If command contains suspicious characters
    """
    # Log command (sanitized)
    logger.info(f"Executing command: {' '.join(cmd)}")

    # Check for shell injection attempts
    for arg in cmd:
        if any(char in arg for char in [';', '|', '&', '$', '`', '>', '<', '\n', '\r']):
            raise ValidationError(f"Invalid characters detected in command argument: {arg}")

    try:
        result = subprocess.run(
            cmd,
            input=input_data.encode() if input_data else None,
            capture_output=True,
            timeout=30,
            check=False
        )

        stdout = result.stdout.decode('utf-8', errors='replace')
        stderr = result.stderr.decode('utf-8', errors='replace')

        if result.returncode != 0:
            logger.error(f"Command failed with code {result.returncode}: {stderr}")

        return result.returncode, stdout, stderr

    except subprocess.TimeoutExpired:
        raise SystemError("Command execution timeout")
    except Exception as e:
        logger.exception(f"Command execution failed: {e}")
        raise SystemError(f"Command execution failed: {str(e)}")


def create_user(
    username: str,
    full_name: Optional[str] = None,
    shell: str = "/bin/bash",
    create_home: bool = True,
    groups: Optional[List[str]] = None
) -> Dict[str, any]:
    """
    Create a new Linux user.

    Args:
        username: Username for new user
        full_name: Full name for GECOS field
        shell: Login shell (default: /bin/bash)
        create_home: Create home directory (default: True)
        groups: Additional groups to add user to

    Returns:
        Dict with user info

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If user creation fails
    """
    validate_username(username)

    # Check if user already exists
    try:
        pwd.getpwnam(username)
        raise ValidationError(f"User already exists: {username}")
    except KeyError:
        pass  # User doesn't exist, proceed

    # Validate shell
    valid_shells = ['/bin/bash', '/bin/sh', '/bin/zsh', '/bin/dash', '/usr/bin/fish']
    if shell not in valid_shells:
        raise ValidationError(f"Invalid shell: {shell}. Must be one of {valid_shells}")

    # Build useradd command
    cmd = ['sudo', 'useradd']

    if create_home:
        cmd.append('-m')

    cmd.extend(['-s', shell])

    if full_name:
        # Sanitize full name
        full_name_clean = re.sub(r'[^\w\s\-\.]', '', full_name)
        cmd.extend(['-c', full_name_clean])

    cmd.append(username)

    # Execute user creation
    returncode, stdout, stderr = run_command(cmd)
    if returncode != 0:
        raise SystemError(f"Failed to create user: {stderr}")

    # Add to additional groups if specified
    if groups:
        for group in groups:
            # Validate group exists
            try:
                grp.getgrnam(group)
            except KeyError:
                logger.warning(f"Group does not exist: {group}")
                continue

            # Add user to group
            returncode, stdout, stderr = run_command(['sudo', 'usermod', '-a', '-G', group, username])
            if returncode != 0:
                logger.error(f"Failed to add user to group {group}: {stderr}")

    # Get user info
    user_info = get_user_info(username)

    logger.info(f"Successfully created user: {username}")
    return user_info


def delete_user(username: str, remove_home: bool = False) -> bool:
    """
    Delete a Linux user.

    Args:
        username: Username to delete
        remove_home: Also remove home directory

    Returns:
        True if successful

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If user deletion fails
    """
    validate_username(username)

    # Check if user exists
    try:
        pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    # Build userdel command
    cmd = ['sudo', 'userdel']

    if remove_home:
        cmd.append('-r')

    cmd.append(username)

    # Execute user deletion
    returncode, stdout, stderr = run_command(cmd)
    if returncode != 0:
        raise SystemError(f"Failed to delete user: {stderr}")

    logger.info(f"Successfully deleted user: {username}")
    return True


def set_password(username: str, password: str) -> bool:
    """
    Set password for a Linux user.

    Args:
        username: Username
        password: New password

    Returns:
        True if successful

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If password change fails
    """
    validate_username(username)

    if not password or len(password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    # Check if user exists
    try:
        pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    # Use chpasswd for batch password setting
    input_data = f"{username}:{password}"

    returncode, stdout, stderr = run_command(['sudo', 'chpasswd'], input_data=input_data)
    if returncode != 0:
        raise SystemError(f"Failed to set password: {stderr}")

    logger.info(f"Successfully set password for user: {username}")
    return True


def add_ssh_key(username: str, ssh_key: str, key_title: Optional[str] = None) -> Dict[str, any]:
    """
    Add SSH public key to user's authorized_keys.

    Args:
        username: Username
        ssh_key: SSH public key
        key_title: Optional title/comment for the key

    Returns:
        Dict with key info

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If key addition fails
    """
    validate_username(username)
    validate_ssh_key(ssh_key)

    # Get user info
    try:
        user_info_pwd = pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    home_dir = user_info_pwd.pw_dir
    ssh_dir = os.path.join(home_dir, '.ssh')
    authorized_keys_file = os.path.join(ssh_dir, 'authorized_keys')

    # Create .ssh directory if it doesn't exist
    if not os.path.exists(ssh_dir):
        os.makedirs(ssh_dir, mode=0o700)
        os.chown(ssh_dir, user_info_pwd.pw_uid, user_info_pwd.pw_gid)
        logger.info(f"Created .ssh directory for user: {username}")

    # Prepare SSH key line
    key_line = ssh_key.strip()
    if key_title:
        # Add title as comment if not already present
        if not key_line.endswith(key_title):
            key_line = f"{key_line} {key_title}"

    # Append key to authorized_keys
    try:
        with open(authorized_keys_file, 'a') as f:
            f.write(key_line + '\n')

        # Set proper permissions
        os.chmod(authorized_keys_file, 0o600)
        os.chown(authorized_keys_file, user_info_pwd.pw_uid, user_info_pwd.pw_gid)

        logger.info(f"Successfully added SSH key for user: {username}")

        return {
            "username": username,
            "key_added": True,
            "key_fingerprint": generate_key_fingerprint(ssh_key),
            "key_title": key_title
        }

    except Exception as e:
        logger.exception(f"Failed to add SSH key: {e}")
        raise SystemError(f"Failed to add SSH key: {str(e)}")


def remove_ssh_key(username: str, key_fingerprint: str) -> bool:
    """
    Remove SSH public key from user's authorized_keys.

    Args:
        username: Username
        key_fingerprint: Fingerprint of key to remove

    Returns:
        True if successful

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If key removal fails
    """
    validate_username(username)

    # Get user info
    try:
        user_info_pwd = pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    home_dir = user_info_pwd.pw_dir
    authorized_keys_file = os.path.join(home_dir, '.ssh', 'authorized_keys')

    if not os.path.exists(authorized_keys_file):
        raise ValidationError(f"No authorized_keys file for user: {username}")

    # Read existing keys
    try:
        with open(authorized_keys_file, 'r') as f:
            lines = f.readlines()

        # Filter out the key with matching fingerprint
        new_lines = []
        removed = False
        for line in lines:
            if line.strip():
                try:
                    if generate_key_fingerprint(line) != key_fingerprint:
                        new_lines.append(line)
                    else:
                        removed = True
                except:
                    # Keep lines that can't be parsed
                    new_lines.append(line)

        if not removed:
            raise ValidationError(f"SSH key not found: {key_fingerprint}")

        # Write back filtered keys
        with open(authorized_keys_file, 'w') as f:
            f.writelines(new_lines)

        logger.info(f"Successfully removed SSH key for user: {username}")
        return True

    except Exception as e:
        logger.exception(f"Failed to remove SSH key: {e}")
        raise SystemError(f"Failed to remove SSH key: {str(e)}")


def list_ssh_keys(username: str) -> List[Dict[str, str]]:
    """
    List all SSH keys for a user.

    Args:
        username: Username

    Returns:
        List of SSH key dicts

    Raises:
        ValidationError: If input validation fails
    """
    validate_username(username)

    # Get user info
    try:
        user_info_pwd = pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    home_dir = user_info_pwd.pw_dir
    authorized_keys_file = os.path.join(home_dir, '.ssh', 'authorized_keys')

    if not os.path.exists(authorized_keys_file):
        return []

    keys = []
    try:
        with open(authorized_keys_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        parts = line.split()
                        key_type = parts[0]
                        key_data = parts[1]
                        key_comment = ' '.join(parts[2:]) if len(parts) > 2 else ''

                        keys.append({
                            "type": key_type,
                            "fingerprint": generate_key_fingerprint(line),
                            "comment": key_comment,
                            "key": line
                        })
                    except:
                        logger.warning(f"Could not parse SSH key line: {line[:50]}...")
    except Exception as e:
        logger.exception(f"Failed to read SSH keys: {e}")
        raise SystemError(f"Failed to read SSH keys: {str(e)}")

    return keys


def set_sudo_permissions(username: str, grant: bool = True) -> bool:
    """
    Grant or revoke sudo permissions for a user.

    Args:
        username: Username
        grant: True to grant sudo, False to revoke

    Returns:
        True if successful

    Raises:
        ValidationError: If input validation fails
        SecurityError: If operation violates security policy
        SystemError: If operation fails
    """
    validate_username(username)

    # Check if user exists
    try:
        pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    if grant:
        # Add user to sudo group
        returncode, stdout, stderr = run_command(['sudo', 'usermod', '-a', '-G', 'sudo', username])
        if returncode != 0:
            raise SystemError(f"Failed to grant sudo permissions: {stderr}")
        logger.info(f"Granted sudo permissions to user: {username}")
    else:
        # Remove user from sudo group
        returncode, stdout, stderr = run_command(['sudo', 'gpasswd', '-d', username, 'sudo'])
        if returncode != 0:
            raise SystemError(f"Failed to revoke sudo permissions: {stderr}")
        logger.info(f"Revoked sudo permissions from user: {username}")

    return True


def get_user_info(username: str) -> Dict[str, any]:
    """
    Get detailed information about a user.

    Args:
        username: Username

    Returns:
        Dict with user information

    Raises:
        ValidationError: If user doesn't exist
    """
    try:
        user_pwd = pwd.getpwnam(username)
    except KeyError:
        raise ValidationError(f"User does not exist: {username}")

    # Get groups
    groups = []
    for group in grp.getgrall():
        if username in group.gr_mem:
            groups.append(group.gr_name)

    # Check if user has sudo
    has_sudo = 'sudo' in groups

    # Get home directory size
    home_size = 0
    if os.path.exists(user_pwd.pw_dir):
        try:
            cmd = ['sudo', 'du', '-sb', user_pwd.pw_dir]
            returncode, stdout, stderr = run_command(cmd)
            if returncode == 0:
                home_size = int(stdout.split()[0])
        except:
            pass

    return {
        "username": username,
        "uid": user_pwd.pw_uid,
        "gid": user_pwd.pw_gid,
        "full_name": user_pwd.pw_gecos,
        "home_dir": user_pwd.pw_dir,
        "shell": user_pwd.pw_shell,
        "groups": groups,
        "has_sudo": has_sudo,
        "home_size_bytes": home_size,
        "is_system_user": user_pwd.pw_uid < MIN_UID
    }


def list_users(include_system: bool = False) -> List[Dict[str, any]]:
    """
    List all users on the system.

    Args:
        include_system: Include system users (UID < 1000)

    Returns:
        List of user info dicts
    """
    users = []
    for user in pwd.getpwall():
        if not include_system and user.pw_uid < MIN_UID:
            continue

        # Skip protected users
        if user.pw_name in PROTECTED_USERS:
            continue

        try:
            users.append(get_user_info(user.pw_name))
        except:
            logger.warning(f"Could not get info for user: {user.pw_name}")

    return users


def generate_key_fingerprint(ssh_key: str) -> str:
    """
    Generate a fingerprint for an SSH key.

    Args:
        ssh_key: SSH public key

    Returns:
        MD5 fingerprint of the key
    """
    import hashlib
    import base64

    try:
        parts = ssh_key.strip().split()
        if len(parts) >= 2:
            key_data = base64.b64decode(parts[1])
            fingerprint = hashlib.md5(key_data).hexdigest()
            # Format as xx:xx:xx:...
            return ':'.join(fingerprint[i:i+2] for i in range(0, len(fingerprint), 2))
    except:
        pass

    # Fallback: hash the entire key
    return hashlib.md5(ssh_key.encode()).hexdigest()[:16]
