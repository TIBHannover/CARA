"""SigLIP 2 (Google): images and texts in one space, so it also embeds text queries."""

from cara.encoders.base import register
from cara.encoders.huggingface import DualEncoder


@register
class SigLIP2(DualEncoder):
    """SigLIP 2 giant at 384 px: `siglip2`, or another checkpoint as `siglip2:<model id>`."""

    name = "siglip2"
    default_model_id = "google/siglip2-giant-opt-patch16-384"
