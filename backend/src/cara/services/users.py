"""Accounts, logging in, and people's roles in studies."""

import hashlib
import hmac
import secrets

from cara.db.models import Role, UserRow
from cara.errors import Conflict, Forbidden, NotFound
from cara.repositories.database import Database


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


class UserService:
    """Accounts and study roles."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, username: str, password: str, is_superuser: bool = False) -> UserRow:
        """Create an account; the password is stored as a salted scrypt hash.

        Raises:
            Conflict: The username is taken.
        """
        if self.db.users.named(username) is not None:
            raise Conflict(f"user {username!r} already exists")
        salt = secrets.token_bytes(16)
        return self.db.users.create(username, salt, _hash_password(password, salt), is_superuser)

    def add_first_admin(self, username: str, password: str) -> bool:
        """Create the first superuser, but only on a database without any users.

        Returns:
            Whether it was created.
        """
        if self.db.users.count():
            return False
        self.add(username, password, is_superuser=True)
        return True

    def usernames(self) -> list[str]:
        """Return every username, in alphabetical order."""
        return self.db.users.usernames()

    def authenticate(self, username: str, password: str) -> UserRow | None:
        """Return the account if the password is right, else None; an unknown username is also None."""
        user = self.db.users.named(username)
        if user is None or not hmac.compare_digest(_hash_password(password, user.salt), user.password_hash):
            return None
        return user

    def get(self, username: str) -> UserRow:
        """Return the account with this username.

        Raises:
            NotFound: There is none.
        """
        user = self.db.users.named(username)
        if user is None:
            raise NotFound(f"user {username!r} doesn't exist")
        return user

    def role_in(self, user: UserRow, study_id: int) -> Role:
        """Return the person's role in the study; superusers are admins of every study.

        Raises:
            NotFound: The study doesn't exist.
            Forbidden: The person isn't a member of it.
        """
        self.db.studies.get(study_id)
        if user.is_superuser:
            return Role.ADMIN
        role = self.db.users.role_in(study_id, user.id)
        if role is None:
            raise Forbidden(f"{user.username} is not a member of study {study_id}")
        return role

    def set_role(self, study_id: int, username: str, role: Role) -> None:
        """Add the person to the study with this role, or change their role.

        Raises:
            NotFound: The study or the user doesn't exist.
        """
        self.db.studies.get(study_id)
        self.db.users.set_role(study_id, self.get(username).id, role)

    def create_account(self, creator: UserRow, username: str, password: str) -> None:
        """Create an account on behalf of `creator`.

        Raises:
            Forbidden: `creator` isn't a superuser.
            Conflict: The username is taken.
        """
        if not creator.is_superuser:
            raise Forbidden("only superusers create accounts")
        self.add(username, password)
