"""Serving a study's images."""

from cara.errors import NotFound
from cara.repositories.database import Database
from cara.repositories.image_store import ImageStore
from cara.services.studies import StudyService


class ImageService:
    """Thumbnails of a study's images, for its members."""

    def __init__(self, db: Database, store: ImageStore) -> None:
        self.db = db
        self.store = store
        self.studies = StudyService(db)

    def thumbnail(self, study_id: int, image_id: int, max_side: int, square: bool) -> bytes:
        """Return an image of the study as a JPEG no larger than `max_side` (see `ImageStore.thumbnail`).

        Raises:
            NotFound: The image isn't one of the study's query or pool images, or its file is missing.
            Forbidden: Its path leads outside the image root.
        """
        image = self.db.datasets.image(image_id)
        if image is None or not self.db.studies.has_image(study_id, image_id):
            raise NotFound(f"image {image_id} is not in study {study_id}")
        dataset = self.db.datasets.get(self.studies.get(study_id).dataset_id)
        return self.store.thumbnail(self.store.path(dataset.path, image.path), max_side, square)
