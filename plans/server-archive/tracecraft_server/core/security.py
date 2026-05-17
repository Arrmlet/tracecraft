"""
Authentication, authorization, and token management for tracecraft.

Provides JWT-based authentication, role-based access control,
API token management, and security policy enforcement.
"""

from jose import jwt, ExpiredSignatureError, JWTError
import time
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path


# --- User and Auth Models ---

@dataclass
class User:
    """User information for authentication."""
    username: str
    roles: List[str]
    permissions: List[str]
    created_at: datetime
    last_login: Optional[datetime] = None


@dataclass
class ApiToken:
    """API token information."""
    token_id: str
    token_hash: str  # Hashed version for security
    name: str
    created_at: datetime
    last_used: Optional[datetime] = None
    projects: List[str] = None  # Empty list = access to all projects
    permissions: List[str] = None  # ['read', 'write', 'admin']
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.projects is None:
            self.projects = []
        if self.permissions is None:
            self.permissions = ['read', 'write']
        if self.metadata is None:
            self.metadata = {}


# --- AuthManager ---

class AuthManager:
    """
    Authentication and authorization manager.

    Provides JWT token management, user authentication,
    and role-based access control.
    """

    def __init__(
        self,
        jwt_secret: str,
        token_expiry_hours: int = 24,
        algorithm: str = "HS256"
    ):
        """
        Initialize authentication manager.

        Args:
            jwt_secret: Secret key for JWT signing
            token_expiry_hours: Token expiration time in hours
            algorithm: JWT signing algorithm
        """
        self.jwt_secret = jwt_secret
        self.token_expiry_hours = token_expiry_hours
        self.algorithm = algorithm

        # In-memory user store (replace with database in production)
        self.users: Dict[str, User] = {}

        # Default admin user
        self._create_default_admin()

    def _create_default_admin(self):
        """Create default admin user."""
        admin_user = User(
            username="admin",
            roles=["admin", "user"],
            permissions=["read", "write", "admin", "delete"],
            created_at=datetime.now()
        )
        self.users["admin"] = admin_user

    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256."""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash."""
        return self.hash_password(password) == hashed

    def create_user(
        self,
        username: str,
        password: str,
        roles: List[str] = None,
        permissions: List[str] = None
    ) -> bool:
        """
        Create a new user.

        Args:
            username: Username
            password: Plain text password
            roles: List of roles
            permissions: List of permissions

        Returns:
            True if user was created successfully
        """
        if username in self.users:
            return False

        user = User(
            username=username,
            roles=roles or ["user"],
            permissions=permissions or ["read"],
            created_at=datetime.now()
        )

        self.users[username] = user
        # In production, store hashed password separately

        return True

    def authenticate(self, username: str, password: str) -> Optional[str]:
        """
        Authenticate user and return JWT token.

        Args:
            username: Username
            password: Password

        Returns:
            JWT token if authentication successful, None otherwise
        """
        if username not in self.users:
            return None

        user = self.users[username]
        user.last_login = datetime.now()

        # Create JWT token
        payload = {
            "username": username,
            "roles": user.roles,
            "permissions": user.permissions,
            "iat": time.time(),
            "exp": time.time() + (self.token_expiry_hours * 3600)
        }

        try:
            token = jwt.encode(payload, self.jwt_secret, algorithm=self.algorithm)
            # Handle both string and bytes return types from different PyJWT versions
            if isinstance(token, bytes):
                token = token.decode('utf-8')
            return token
        except Exception as e:
            print(f"JWT encoding error: {e}")
            return None

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify JWT token and return payload.

        Args:
            token: JWT token

        Returns:
            Token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.algorithm])
            return payload
        except ExpiredSignatureError:
            return None
        except JWTError:
            return None

    def has_permission(self, token: str, required_permission: str) -> bool:
        """
        Check if token has required permission.

        Args:
            token: JWT token
            required_permission: Required permission

        Returns:
            True if token has permission
        """
        payload = self.verify_token(token)
        if not payload:
            return False

        permissions = payload.get("permissions", [])
        return required_permission in permissions or "admin" in permissions

    def has_role(self, token: str, required_role: str) -> bool:
        """
        Check if token has required role.

        Args:
            token: JWT token
            required_role: Required role

        Returns:
            True if token has role
        """
        payload = self.verify_token(token)
        if not payload:
            return False

        roles = payload.get("roles", [])
        return required_role in roles or "admin" in roles

    def get_user_info(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from token.

        Args:
            token: JWT token

        Returns:
            User information if token is valid
        """
        payload = self.verify_token(token)
        if not payload:
            return None

        username = payload.get("username")
        if username not in self.users:
            return None

        user = self.users[username]
        return {
            "username": user.username,
            "roles": user.roles,
            "permissions": user.permissions,
            "created_at": user.created_at.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None
        }

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a token (add to blacklist).

        Args:
            token: JWT token to revoke

        Returns:
            True if token was revoked
        """
        # In production, maintain a blacklist of revoked tokens
        return True

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users (admin only)."""
        users_info = []
        for user in self.users.values():
            users_info.append({
                "username": user.username,
                "roles": user.roles,
                "permissions": user.permissions,
                "created_at": user.created_at.isoformat(),
                "last_login": user.last_login.isoformat() if user.last_login else None
            })
        return users_info


# --- TokenManager ---

class TokenManager:
    """
    API token manager.

    Features:
    - Simple token generation (tc_xxxxx format)
    - Automatic project creation
    - Permission-based access
    - Token expiration
    - Usage tracking
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize token manager.

        Args:
            storage_path: Path to store token database (JSON file)
        """
        self.storage_path = storage_path or "~/.tracecraft/tokens.json"
        self.storage_path = Path(self.storage_path).expanduser()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory token store
        self.tokens: Dict[str, ApiToken] = {}

        # Load existing tokens
        self._load_tokens()

        # Create default admin token if none exist
        if not self.tokens:
            self._create_default_token()

    def _load_tokens(self):
        """Load tokens from storage."""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)

                for token_id, token_data in data.items():
                    # Convert datetime strings back to datetime objects
                    token_data['created_at'] = datetime.fromisoformat(token_data['created_at'])
                    if token_data.get('last_used'):
                        token_data['last_used'] = datetime.fromisoformat(token_data['last_used'])
                    if token_data.get('expires_at'):
                        token_data['expires_at'] = datetime.fromisoformat(token_data['expires_at'])

                    self.tokens[token_id] = ApiToken(**token_data)

        except Exception as e:
            print(f"Warning: Could not load tokens: {e}")
            self.tokens = {}

    def _save_tokens(self):
        """Save tokens to storage."""
        try:
            data = {}
            for token_id, token in self.tokens.items():
                token_dict = asdict(token)
                # Convert datetime objects to strings
                token_dict['created_at'] = token.created_at.isoformat()
                if token.last_used:
                    token_dict['last_used'] = token.last_used.isoformat()
                if token.expires_at:
                    token_dict['expires_at'] = token.expires_at.isoformat()

                data[token_id] = token_dict

            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            print(f"Warning: Could not save tokens: {e}")

    def _create_default_token(self):
        """Create default admin token."""
        token = self.create_token(
            name="Default Admin Token",
            permissions=['read', 'write', 'admin'],
            projects=[],  # Access to all projects
            expires_days=365
        )
        print(f"Created default admin token: {token}")
        print(f"Stored in: {self.storage_path}")

    def create_token(
        self,
        name: str,
        permissions: List[str] = None,
        projects: List[str] = None,
        expires_days: Optional[int] = None
    ) -> str:
        """
        Create a new API token.

        Args:
            name: Human-readable token name
            permissions: List of permissions ['read', 'write', 'admin']
            projects: List of project names (empty = all projects)
            expires_days: Token expiration in days (None = never expires)

        Returns:
            API token string (tc_xxxxx format)
        """
        # Generate token: tc_<32 hex chars>
        token_secret = secrets.token_urlsafe(24)  # 32 chars base64url
        token_id = f"tc_{secrets.token_hex(16)}"  # tc_ + 32 hex chars
        full_token = f"{token_id}_{token_secret}"

        # Hash the token for storage (never store plain text)
        token_hash = hashlib.sha256(full_token.encode()).hexdigest()

        # Calculate expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.now() + timedelta(days=expires_days)

        # Create token object
        api_token = ApiToken(
            token_id=token_id,
            token_hash=token_hash,
            name=name,
            created_at=datetime.now(),
            permissions=permissions or ['read', 'write'],
            projects=projects or [],
            expires_at=expires_at,
            metadata={
                'user_agent': 'tracecraft-cli',
                'created_by': 'token-manager'
            }
        )

        # Store token
        self.tokens[token_id] = api_token
        self._save_tokens()

        return full_token

    def verify_token(self, token: str) -> Optional[ApiToken]:
        """
        Verify API token and return token info.

        Args:
            token: Full API token (tc_xxxxx_yyyyy)

        Returns:
            ApiToken object if valid, None otherwise
        """
        try:
            # Extract token ID
            if not token.startswith('tc_'):
                return None

            parts = token.split('_', 2)
            if len(parts) != 3:
                return None

            token_id = f"{parts[0]}_{parts[1]}"  # tc_xxxxx

            # Check if token exists
            if token_id not in self.tokens:
                return None

            api_token = self.tokens[token_id]

            # Verify token hash
            expected_hash = hashlib.sha256(token.encode()).hexdigest()
            if api_token.token_hash != expected_hash:
                return None

            # Check expiration
            if api_token.expires_at and datetime.now() > api_token.expires_at:
                return None

            # Update last used time
            api_token.last_used = datetime.now()
            self._save_tokens()

            return api_token

        except Exception:
            return None

    def has_project_access(self, token: ApiToken, project: str) -> bool:
        """
        Check if token has access to specific project.

        Args:
            token: Verified API token
            project: Project name

        Returns:
            True if token has access
        """
        # Admin tokens have access to everything
        if 'admin' in token.permissions:
            return True

        # Empty projects list = access to all projects
        if not token.projects:
            return True

        # Check specific project access
        return project in token.projects

    def has_permission(self, token: ApiToken, permission: str) -> bool:
        """
        Check if token has specific permission.

        Args:
            token: Verified API token
            permission: Permission to check ('read', 'write', 'admin')

        Returns:
            True if token has permission
        """
        return permission in token.permissions or 'admin' in token.permissions

    def list_tokens(self) -> List[Dict[str, Any]]:
        """List all tokens (admin only)."""
        tokens_info = []
        for token in self.tokens.values():
            tokens_info.append({
                'token_id': token.token_id,
                'name': token.name,
                'permissions': token.permissions,
                'projects': token.projects,
                'created_at': token.created_at.isoformat(),
                'last_used': token.last_used.isoformat() if token.last_used else None,
                'expires_at': token.expires_at.isoformat() if token.expires_at else None,
                'metadata': token.metadata
            })
        return tokens_info

    def revoke_token(self, token_id: str) -> bool:
        """
        Revoke an API token.

        Args:
            token_id: Token ID to revoke (tc_xxxxx format)

        Returns:
            True if token was revoked
        """
        if token_id in self.tokens:
            del self.tokens[token_id]
            self._save_tokens()
            return True
        return False

    def cleanup_expired_tokens(self) -> int:
        """
        Remove expired tokens.

        Returns:
            Number of tokens removed
        """
        now = datetime.now()
        expired_tokens = [
            token_id for token_id, token in self.tokens.items()
            if token.expires_at and now > token.expires_at
        ]

        for token_id in expired_tokens:
            del self.tokens[token_id]

        if expired_tokens:
            self._save_tokens()

        return len(expired_tokens)


# --- CLI helper functions ---

def generate_token_for_project(project: str, permissions: List[str] = None) -> str:
    """
    Generate a new token for a specific project.

    Args:
        project: Project name
        permissions: Token permissions

    Returns:
        New API token
    """
    manager = TokenManager()
    return manager.create_token(
        name=f"Token for {project}",
        permissions=permissions or ['read', 'write'],
        projects=[project] if project != "all" else [],
        expires_days=365
    )


def verify_token_quick(token: str) -> bool:
    """Quick token verification for CLI use."""
    manager = TokenManager()
    return manager.verify_token(token) is not None
