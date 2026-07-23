"""The synthetic card generator must emit well-formed OBB labels whose classes
match the detector's CLASS_MAP — otherwise training produces a detector the
pipeline can't consume."""
import random

import pytest

from scripts.synth_cards import (KIR_CLASSES, SIM_CLASSES, RENDERERS, augment,
                                 fonts, render_kir, render_sim)
from app.parser.field_detector import CLASS_MAP


@pytest.fixture(autouse=True)
def _seed():
    random.seed(1234)


@pytest.mark.parametrize("doc_type,classes", [("SIM", SIM_CLASSES), ("KIR", KIR_CLASSES)])
def test_classes_match_detector_class_map(doc_type, classes):
    """Every synthetic class must be a key the detector maps to a field."""
    mapped = CLASS_MAP[doc_type]
    for c in classes:
        assert c in mapped, f"{doc_type} class {c!r} missing from field_detector CLASS_MAP"


@pytest.mark.parametrize("render,classes", [(render_sim, SIM_CLASSES), (render_kir, KIR_CLASSES)])
def test_flat_render_boxes_are_valid(render, classes):
    img, boxes = render(fonts())
    assert boxes, "no field boxes produced"
    W, H = img.size
    seen = set()
    for cls, corners in boxes:
        assert 0 <= cls < len(classes)
        seen.add(cls)
        assert len(corners) == 4
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        # box inside the card and non-degenerate
        assert min(xs) >= -5 and max(xs) <= W + 5
        assert min(ys) >= -5 and max(ys) <= H + 5
        assert max(xs) - min(xs) > 3 and max(ys) - min(ys) > 3
    # the value-bearing classes should all appear at least once
    assert len(seen) >= len(classes) - 1


@pytest.mark.parametrize("doc_type", ["SIM", "KIR"])
def test_augmented_labels_are_normalised_obb(doc_type):
    render, classes = RENDERERS[doc_type]
    card, boxes = render(fonts())
    _im, lines = augment(card, boxes)
    assert lines, "augmentation dropped every box"
    for ln in lines:
        parts = ln.split()
        assert len(parts) == 9, f"OBB line must be class + 8 coords, got {len(parts)}"
        cls = int(parts[0])
        assert 0 <= cls < len(classes)
        coords = [float(x) for x in parts[1:]]
        assert all(0.0 <= v <= 1.0 for v in coords), "coords must be normalised to [0,1]"


def test_augment_output_size_matches_pil():
    card, boxes = render_sim(fonts())
    im, _lines = augment(card, boxes)
    assert im.size[0] > 0 and im.size[1] > 0
    assert im.mode in ("RGB", "L")
