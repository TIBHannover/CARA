"""The base of every repository: one aggregate root, and the basic operations on it."""

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from cara.db.models import Base
from cara.errors import NotFound


class Repository[T: Base]:
    """The rows of one aggregate root, through one session; subclasses add the aggregate's own queries.

    Attributes:
        model: The root's table.
        noun: How error messages name a row of it, such as "study".
    """

    model: type[T]
    noun: str

    def __init__(self, session: Session) -> None:
        self.session = session

    def find(self, id_: int) -> T | None:
        """Return the row with this id, or None."""
        return self.session.get(self.model, id_)

    def get(self, id_: int) -> T:
        """Return the row with this id.

        Raises:
            NotFound: There is none; the message names the noun and the id.
        """
        row = self.find(id_)
        if row is None:
            raise NotFound(f"{self.noun} {id_} doesn't exist")
        return row

    def add(self, row: T) -> T:
        """Add a row and flush, so it has its id."""
        self.session.add(row)
        self.session.flush()
        return row

    def list_all(self) -> list[T]:
        """Return every row, oldest first."""
        return list(self.session.scalars(select(self.model).order_by(*inspect(self.model).primary_key)))
