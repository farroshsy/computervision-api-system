"""Multi-document splitting: cluster logic (unit) via synthetic geometry."""
from app.parser.multi_doc import split_vertical_clusters


def _item(text, cy, h=20.0, conf=0.95):
    return {"text": text, "conf": conf, "cy": cy, "h": h}


def test_split_on_large_gap():
    items = [_item(f"a{i}", 100 + i * 25) for i in range(5)] + \
            [_item(f"b{i}", 600 + i * 25) for i in range(5)]
    clusters = split_vertical_clusters(items)
    assert len(clusters) == 2
    assert len(clusters[0]) == 5 and len(clusters[1]) == 5


def test_no_split_on_normal_spacing():
    items = [_item(f"a{i}", 100 + i * 30) for i in range(10)]
    assert len(split_vertical_clusters(items)) == 1


def test_tiny_input_stays_single():
    items = [_item("a", 10), _item("b", 500)]
    assert len(split_vertical_clusters(items)) == 1
