"""Image files on disk, under the image root."""

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

from cara.errors import Forbidden, NotFound


class ImageStore:
    """The image files of every dataset, under one root folder (`CARA_IMAGE_ROOT`)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, dataset_folder: str, image_path: str) -> Path:
        """Return an image's file, from its dataset's folder and its path in the dataset.

        Raises:
            Forbidden: The path leads outside the image root (such as `../`), which the API must never serve.
            NotFound: The file is missing on the server; the message names the path.
        """
        path = (self.root / dataset_folder / image_path).resolve()
        if not path.is_relative_to(self.root):
            raise Forbidden(f"image path {image_path!r} points outside the image root")
        if not path.is_file():
            raise NotFound(f"image file missing on the server: {dataset_folder}/{image_path}")
        return path

    def thumbnail(self, path: Path, max_side: int, square: bool) -> bytes:
        """Return the image as a JPEG no larger than `max_side` on either side.

        Results are cached in memory for the life of the process (the last 20,000), so a changed file shows
        its old thumbnail until the API restarts.

        Args:
            path: The image file, as `path()` returns it.
            max_side: The longest side in pixels.
            square: Crop to a centred square, so every tile in a grid has the same size and no padding bars;
                otherwise keep the aspect ratio.

        Raises:
            PIL.UnidentifiedImageError: The file isn't an image Pillow can read.
        """
        return _thumbnail(path, max_side, square)


@lru_cache(maxsize=20_000)
def _thumbnail(path: Path, max_side: int, square: bool) -> bytes:
    with Image.open(path) as source:
        rgb = source.convert("RGB")
    if square:
        rgb = ImageOps.fit(rgb, (max_side, max_side))
    else:
        rgb.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()
