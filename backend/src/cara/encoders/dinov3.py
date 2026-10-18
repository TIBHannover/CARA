"""DINOv3 (Meta): image-only; publications that use it must acknowledge DINOv3 (see its licence)."""

from cara.encoders.base import register
from cara.encoders.huggingface import ClsEncoder


@register
class DINOv3(ClsEncoder):
    """DINOv3 ViT-B/16, the CLS token as the image embedding: `dinov3`, or `dinov3:<model id>`."""

    name = "dinov3"
    default_model_id = "facebook/dinov3-vitb16-pretrain-lvd1689m"


@register
class DINOv3Giant(DINOv3):
    """DINOv3 ViT-7B/16, for the best image embeddings on a large GPU: `dinov3-7b`."""

    name = "dinov3-7b"
    default_model_id = "facebook/dinov3-vit7b16-pretrain-lvd1689m"
