"""The unit of work: one session and the repositories that share it."""

from sqlalchemy.orm import Session

from cara.repositories.datasets import Datasets
from cara.repositories.judgments import Judgments
from cara.repositories.studies import Studies
from cara.repositories.users import Users


class Database:
    """One session and its repositories, as services use them: `db.studies.get(3)`.

    The caller owns the session and its transaction (the API opens one per request, the CLI one per command);
    repositories only flush.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = Users(session)
        self.datasets = Datasets(session)
        self.studies = Studies(session)
        self.judgments = Judgments(session)
