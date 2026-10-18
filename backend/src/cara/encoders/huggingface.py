"""Any model from the Hugging Face hub: image-only models (`hf-cls`) and text–image models (`hf-dual`).

Model-specific encoders (`dinov3.py`, `siglip.py`) subclass these with a name and a default model.
"""

from functools import cached_property
from pathlib import Path

import numpy as np
import numpy.typing as npt
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from transformers import AutoImageProcessor, AutoModel, AutoProcessor
from transformers.modeling_outputs import BaseModelOutputWithPooling

from cara.encoders.base import Encoder, register


def device() -> torch.device:
    """Return the GPU if there is one, else the CPU."""
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class _Images(Dataset[torch.Tensor]):
    def __init__(self, paths: list[Path], processor: AutoImageProcessor) -> None:
        self.paths = paths
        self.processor = processor

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> torch.Tensor:
        with Image.open(self.paths[index]) as img:
            pixels: torch.Tensor = self.processor(images=img.convert("RGB"), return_tensors="pt")[  # type: ignore[operator]
                "pixel_values"
            ][0]
        return pixels


def _normalise(output: torch.Tensor | BaseModelOutputWithPooling) -> npt.NDArray[np.float16]:
    """Scale the model's embeddings to unit length; transformers 5 or later wraps them as `pooler_output`."""
    features_bd = output if isinstance(output, torch.Tensor) else output.pooler_output
    if features_bd is None:
        raise ValueError("the model returned no pooled embedding")
    return torch.nn.functional.normalize(features_bd.float(), dim=1).cpu().numpy().astype(np.float16)


class HuggingFaceEncoder(Encoder):
    """A model from the Hugging Face hub, loaded on first use, in bfloat16 on a GPU.

    Subclasses say which features of the model are the image embedding.
    """

    @cached_property
    def model(self) -> torch.nn.Module:
        """Return the model, downloaded on first use (gated models need `HF_TOKEN`)."""
        dtype = torch.bfloat16 if device().type == "cuda" else torch.float32
        model: torch.nn.Module = AutoModel.from_pretrained(self.model_id, dtype=dtype).to(device()).eval()
        return model

    def _image_features(self, pixels_bchw: torch.Tensor) -> torch.Tensor | BaseModelOutputWithPooling:
        raise NotImplementedError

    def encode_images(self, paths: list[Path], batch_size: int, num_workers: int) -> npt.NDArray[np.float16]:
        """Return one unit-length embedding per image file, in batches, with a progress line every minute."""
        processor = AutoImageProcessor.from_pretrained(self.model_id)  # type: ignore[no-untyped-call]
        loader = DataLoader(_Images(paths, processor), batch_size=batch_size, num_workers=num_workers)
        chunks = []
        with (
            torch.inference_mode(),
            torch.autocast(device().type, dtype=torch.bfloat16, enabled=device().type == "cuda"),
        ):
            for pixels_bchw in tqdm(loader, desc=f"{self.model_id}: {len(paths)} images", mininterval=60):
                chunks.append(_normalise(self._image_features(pixels_bchw.to(device()))))
        return np.concatenate(chunks)


@register
class ClsEncoder(HuggingFaceEncoder):
    """Any image-only model whose image embedding is the CLS token, such as DINOv3: `hf-cls:<model id>`."""

    name = "hf-cls"

    def _image_features(self, pixels_bchw: torch.Tensor) -> torch.Tensor:
        cls_bd: torch.Tensor = self.model(pixel_values=pixels_bchw).last_hidden_state[:, 0]
        return cls_bd


@register
class DualEncoder(HuggingFaceEncoder):
    """Any text–image model with image and text features in one space, such as CLIP: `hf-dual:<model id>`."""

    name = "hf-dual"
    cross_modal = True

    @property
    def text_length(self) -> int:
        """Return the tokens a text is cut or padded to: 64 for SigLIP models, else 77 (CLIP's)."""
        return 64 if "siglip" in self.model_id else 77

    def _image_features(self, pixels_bchw: torch.Tensor) -> torch.Tensor | BaseModelOutputWithPooling:
        features: torch.Tensor | BaseModelOutputWithPooling = self.model.get_image_features(  # type: ignore[operator]
            pixel_values=pixels_bchw
        )
        return features

    def encode_texts(self, texts: list[str], batch_size: int) -> npt.NDArray[np.float16]:
        """Return one unit-length embedding per text.

        Texts are cut to `text_length` tokens.
        """
        processor = AutoProcessor.from_pretrained(self.model_id)  # type: ignore[no-untyped-call]
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                tokens = processor(
                    text=texts[start : start + batch_size],
                    padding="max_length",
                    truncation=True,
                    max_length=self.text_length,
                    return_tensors="pt",
                ).to(device())
                chunks.append(_normalise(self.model.get_text_features(**tokens)))  # type: ignore[operator]
        return np.concatenate(chunks)
