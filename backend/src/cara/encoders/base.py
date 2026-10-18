"""What every encoder is: its name, its model, embeddings of images and maybe texts; and the registry."""

from pathlib import Path
from typing import ClassVar

import numpy as np
import numpy.typing as npt


class Encoder:
    """An image encoder, and maybe a text encoder: turns files or texts into unit-length embeddings.

    Subclasses set `name`, implement `encode_images` (and `encode_texts` if they read text), and are decorated
    with `register`. A study names an encoder as `<name>` (its default model) or `<name>:<model id>`.

    Attributes:
        name: The key a study's YAML and `cara encode --encoder` name it by.
        default_model_id: The model `<name>` alone loads; None if a model id must be given.
        cross_modal: Whether it also embeds texts into the same space, as text queries need.
        model_id: The model it loads, such as a Hugging Face id.
    """

    name: ClassVar[str]
    default_model_id: ClassVar[str | None] = None
    cross_modal: ClassVar[bool] = False

    def __init__(self, model_id: str | None = None) -> None:
        """Use `model_id`, else the encoder's default model.

        Raises:
            ValueError: There is neither; the message shows how to give one.
        """
        model_id = model_id or self.default_model_id
        if model_id is None:
            raise ValueError(f"encoder {self.name!r} needs a model id: '{self.name}:<model id>'")
        self.model_id = model_id

    def encode_images(self, paths: list[Path], batch_size: int, num_workers: int) -> npt.NDArray[np.float16]:
        """Return one unit-length embedding per image file, in the order given."""
        raise NotImplementedError

    def encode_texts(self, texts: list[str], batch_size: int) -> npt.NDArray[np.float16]:
        """Return one unit-length embedding per text, in the order given.

        Raises:
            ValueError: The encoder reads images only (the default).
        """
        raise ValueError(f"{self.model_id} is an image-only encoder; text queries need a cross-modal one")


ENCODERS: dict[str, type[Encoder]] = {}
"""Every registered encoder, by its name."""


def register[E: Encoder](cls: type[E]) -> type[E]:
    """Register an encoder under its `name`, so studies and `cara encode` can use it.

    Raises:
        TypeError: The class sets no `name`.
        ValueError: Another class is registered under the same name (a subclass that forgot its own).
    """
    name = cls.__dict__.get("name")
    if not isinstance(name, str):
        raise TypeError(f"{cls.__name__} needs its own class attribute `name` to be registered")
    if name in ENCODERS:
        raise ValueError(f"encoder {name!r} is registered twice: {ENCODERS[name].__name__}, {cls.__name__}")
    ENCODERS[name] = cls
    return cls
