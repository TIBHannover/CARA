"""Grouping a pool's images, so annotators can label similar images with one click.

Every module in this package is imported here, and each method in it registers itself with `@register`
under its `method` key. `GroupingSettings` is the union of the registered methods: a study's
`grouping.method` picks the class, and pydantic builds it.

To add a method, write a module here with one `GroupingMethod` subclass, a `method: Literal["<key>"]` field
and `@register` on it; nothing else changes. The admin's simulator compares the methods it has options for
(`services/simulator/plan.py`).
"""

import importlib
import pkgutil
from typing import TYPE_CHECKING, Annotated, Union

from pydantic import Field

from cara.grouping.base import (
    METHODS,
    GroupingMethod,
    Linkage,
    PoolGroups,
    bisect,
    cap,
    find_solos,
    register,
    scores,
)

for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module.name}")

if TYPE_CHECKING:
    GroupingSettings = GroupingMethod
else:
    GroupingSettings = Annotated[Union[tuple(METHODS.values())], Field(discriminator="method")]  # noqa: UP007
"""Every registered grouping method, told apart by its `method` key."""

__all__ = [
    "METHODS",
    "GroupingMethod",
    "GroupingSettings",
    "Linkage",
    "PoolGroups",
    "bisect",
    "cap",
    "find_solos",
    "register",
    "scores",
]
