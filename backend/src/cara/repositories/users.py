"""Accounts and study membership."""

from sqlalchemy import func, select

from cara.db.models import Role, StudyMemberRow, UserRow
from cara.repositories.base import Repository


class Users(Repository[UserRow]):
    """Accounts, and who has which role in which study."""

    model = UserRow
    noun = "user"

    def named(self, username: str) -> UserRow | None:
        """Return the account with this username, or None if there is none."""
        return self.session.scalar(select(UserRow).where(UserRow.username == username))

    def usernames(self) -> list[str]:
        """Return every username, in alphabetical order."""
        return list(self.session.scalars(select(UserRow.username).order_by(UserRow.username)))

    def count(self) -> int:
        """Count the accounts."""
        return self.session.scalar(select(func.count()).select_from(UserRow)) or 0

    def create(self, username: str, salt: bytes, password_hash: bytes, is_superuser: bool) -> UserRow:
        """Add an account and flush, so it has its id.

        Raises:
            sqlalchemy.exc.IntegrityError: The username is taken.
        """
        return self.add(
            UserRow(username=username, salt=salt, password_hash=password_hash, is_superuser=is_superuser)
        )

    def role_in(self, study_id: int, user_id: int) -> Role | None:
        """Return the person's role in the study, or None if they aren't a member."""
        return self.session.scalar(
            select(StudyMemberRow.role).where(
                StudyMemberRow.study_id == study_id, StudyMemberRow.user_id == user_id
            )
        )

    def set_role(self, study_id: int, user_id: int, role: Role) -> None:
        """Add the person to the study with this role, or change their role if they are a member already."""
        self.session.merge(StudyMemberRow(study_id=study_id, user_id=user_id, role=role))

    def members(self, study_id: int) -> list[tuple[str, Role]]:
        """Return the study's members and their roles, by username."""
        rows = self.session.execute(
            select(UserRow.username, StudyMemberRow.role)
            .join(StudyMemberRow, StudyMemberRow.user_id == UserRow.id)
            .where(StudyMemberRow.study_id == study_id)
            .order_by(UserRow.username)
        )
        return [(username, role) for username, role in rows]
