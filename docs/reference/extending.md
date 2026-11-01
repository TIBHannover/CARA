# Extending CARA

CARA has two extension points, encoders and grouping methods. Each is one module, and CARA imports every module in
those folders, so nothing else needs to change.

## A grouping method

Add a module to `backend/src/cara/grouping/` with one `GroupingMethod` subclass, decorated with `@register`. It needs a
`method` key, its settings, a `label` and a `partition`. This minimal example makes groups of a fixed size:

```python
"""Fixed chunks: groups of `size` images, in the order of the embeddings."""

from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field

from cara.grouping.base import GroupingMethod, register


@register
class Chunks(GroupingMethod):
    method: Literal["chunks"]
    size: int = Field(default=8, ge=2)

    def label(self) -> str:
        return f"chunks of {self.size}"

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        rows = list(range(len(emb_nd)))
        return [rows[i : i + self.size] for i in range(0, len(rows), self.size)]
```

A study can then use it with `grouping: {method: chunks, size: 8}`. CARA does the shared steps itself: it sets aside the
ungrouped images, caps each group at `max_size`, and orders the groups by similarity to the query.

To compare the method in the simulator as well, add its options to `services/simulator/plan.py`.

## An encoder

| To add | Change |
|---|---|
| A Hugging Face model | Nothing: use `encoder: hf-cls:<model id>` (DINO-style) or `hf-dual:<model id>` (CLIP-style). |
| A short name for a Hugging Face model | A module like `encoders/clip.py`: a subclass of `ClsEncoder` or `DualEncoder` with `name`, `default_model_id` and `@register`. |
| Another family, such as timm or OpenCLIP | A module in `backend/src/cara/encoders/` with one `Encoder` subclass and `@register`. It needs `name` and `encode_images`, and `encode_texts` if it reads text (see `base.py`). |

## Other changes

| To add | Change |
|---|---|
| An export | A function in `core/export.py` and a branch in `services/admin.py`. |
| Another front end | A client for the API. Its schema is at <http://localhost:8000/docs>. |
