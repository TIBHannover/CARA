"""Encoders that embed a dataset's images and text queries (`cara encode`).

Every module in this package is imported here, and each encoder in it registers itself with `@register` under
its `name`. A study names an encoder as `<name>` (its default model, such as `dinov3`) or `<name>:<model id>`
(such as `hf-dual:openai/clip-vit-large-patch14`); `build_encoder` makes it.

To add an encoder, write a module here with an `Encoder` subclass (or a subclass of `ClsEncoder` or
`DualEncoder` for a Hugging Face model), a `name`, and `@register` on it; nothing else changes. Importing this
package imports torch, so it needs the `encode` extra.
"""

import importlib
import pkgutil

from cara.encoders.base import ENCODERS, Encoder, register
from cara.encoders.huggingface import device

for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module.name}")


def build_encoder(name: str) -> Encoder:
    """Make the encoder a name stands for: `<name>` or `<name>:<model id>`.

    The model itself is loaded on first use.

    Raises:
        ValueError: The name isn't registered (the message lists those that are), or it needs a model id.
    """
    key, _, model_id = name.partition(":")
    if key not in ENCODERS:
        raise ValueError(f"unknown encoder {key!r}; registered: {sorted(ENCODERS)}")
    return ENCODERS[key](model_id or None)


__all__ = ["ENCODERS", "Encoder", "build_encoder", "device", "register"]
