from dataclasses import dataclass

from sqlalchemy import update
from sqlmodel import Session

from app.models.dataset import Dataset, utc_now


class DatasetRevisionError(RuntimeError):
    """Raised when a revision cannot be advanced for an existing dataset."""


def bump_dataset_revision(session: Session, dataset_id: int) -> int:
    """Advance a dataset revision inside the caller's current transaction."""
    statement = (
        update(Dataset)
        .where(Dataset.id == dataset_id)
        .values(revision=Dataset.revision + 1, updated_at=utc_now())
        .returning(Dataset.revision)
    )
    revision = session.exec(statement).scalar_one_or_none()
    if revision is None:
        raise DatasetRevisionError(f"Dataset {dataset_id} was not found.")
    return int(revision)


@dataclass
class DatasetRevisionTracker:
    """Advance at most once across a logical operation with multiple commits."""

    dataset_id: int
    revision: int | None = None

    def bump_once(self, session: Session) -> int:
        if self.revision is None:
            self.revision = bump_dataset_revision(session, self.dataset_id)
        return self.revision
