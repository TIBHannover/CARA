"""Depth pooling: several encoders' top images as one union."""

from cara.core.pooling import union_pool


def test_union_keeps_each_image_once_in_order_of_its_best_rank() -> None:
    # 2 is first for the second encoder, 4 second; 3 is only third for the first encoder.
    assert union_pool([[1, 2, 3], [2, 4]]) == [1, 2, 4, 3]
    assert union_pool([[5, 6]]) == [5, 6]
