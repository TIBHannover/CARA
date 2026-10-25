"""CLIP (OpenAI): images and texts in one space; small enough for a CPU."""

from cara.encoders.base import register
from cara.encoders.huggingface import DualEncoder


@register
class CLIP(DualEncoder):
    """CLIP ViT-B/16: `clip`, or another checkpoint as `clip:<model id>`."""

    name = "clip"
    default_model_id = "openai/clip-vit-base-patch16"
