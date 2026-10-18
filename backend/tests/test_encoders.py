"""The encoder registry, without loading any model weights (skipped without the `encode` extra)."""

import pytest

encoders = pytest.importorskip("cara.encoders", reason="needs the encode extra (torch, transformers)")


def test_named_models_and_specs_resolve_without_loading_weights() -> None:
    named = encoders.build_encoder("dinov3-7b")
    assert (named.model_id, named.cross_modal) == ("facebook/dinov3-vit7b16-pretrain-lvd1689m", False)
    spec = encoders.build_encoder("hf-dual:openai/clip-vit-base-patch32")
    assert (spec.model_id, spec.cross_modal) == ("openai/clip-vit-base-patch32", True)


def test_a_checkpoint_replaces_the_default_model() -> None:
    encoder = encoders.build_encoder("siglip2:google/siglip2-base-patch16-224")
    assert (type(encoder).__name__, encoder.model_id) == ("SigLIP2", "google/siglip2-base-patch16-224")


def test_unknown_names_and_missing_model_ids_fail_with_the_fix() -> None:
    with pytest.raises(ValueError, match="unknown encoder 'timm'.*'dinov3'"):
        encoders.build_encoder("timm:resnet50")
    with pytest.raises(ValueError, match="'hf-cls:<model id>'"):
        encoders.build_encoder("hf-cls")


def test_a_subclass_without_its_own_name_is_not_registered_twice() -> None:
    class Unnamed(encoders.ENCODERS["dinov3"]):  # type: ignore[misc]
        pass

    with pytest.raises(TypeError, match="Unnamed needs its own class attribute `name`"):
        encoders.register(Unnamed)


def test_image_only_encoders_refuse_text() -> None:
    with pytest.raises(ValueError, match="image-only"):
        encoders.build_encoder("dinov3").encode_texts(["a vase"], 8)
