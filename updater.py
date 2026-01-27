import subprocess
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Global flag to avoid repeated checks
GIT_AVAILABLE = None

import sys

def is_git_available():
    global GIT_AVAILABLE
    if GIT_AVAILABLE is not None:
        return GIT_AVAILABLE
    try:
        # Suppress output to avoid "fatal: not a git repository" spam in logs
        subprocess.run(['git', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        GIT_AVAILABLE = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        GIT_AVAILABLE = False
    return GIT_AVAILABLE

def run_git_command(args, cwd=None):
    """Run a git command and return output."""
    if not is_git_available():
        return None

    try:
        if cwd is None:
            cwd = os.getcwd()
            
        result = subprocess.run(
            ['git'] + args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Only log if it's NOT a "not a git repo" error which is expected in frozen mode
        if "not a git repository" not in e.stderr:
            logger.error(f"Git command failed: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"Error running git: {e}")
        return None


def get_current_version_hash():
    """Returns the current version (tag or short hash)."""
    # Try to get exact tag
    tag = run_git_command(['describe', '--tags', '--exact-match', 'HEAD'])
    if tag:
        return tag
    
    # Fallback to short hash
    return run_git_command(['rev-parse', '--short', 'HEAD'])

def get_current_commit_message():
    """Returns the current commit message."""
    return run_git_command(['log', '-1', '--pretty=%B'])

def check_for_updates():
    """
    Checks if there are updates available on remote.
    Returns:
        dict: {
            'update_available': bool,
            'current_version': str,
            'remote_version': str,
            'commits_behind': int,
            'changelog': list of str
        }
    """
    if not is_git_available():
        return {'update_available': False, 'error': 'Git not installed'}
    
    # Fetch latest usage
    run_git_command(['fetch'])
    
    current = get_current_version_hash()
    
    # Check status relative to upstream
    # Assumes 'origin/main' is the upstream branch
    status_output = run_git_command(['rev-list', '--left-right', '--count', 'HEAD...origin/main'])
    
    if not status_output:
        return {'update_available': False, 'error': 'Could not check updates'}
        
    ahead, behind = map(int, status_output.split())
    
    update_available = behind > 0
    
    changelog = []
    if update_available:
        # Get log of what's new
        log_output = run_git_command(['log', 'HEAD..origin/main', '--pretty=format:%h - %s'])
        if log_output:
            changelog = log_output.split('\n')
            
    return {
        'update_available': update_available,
        'current_version': current,
        'commits_behind': behind,
        'changelog': changelog
    }

def perform_update():
    """
    Pulls changes from remote.
    Returns (success, message)
    """
    result = run_git_command(['pull'])
    if result:
        return True, result
    return False, "Failed to pull updates."
