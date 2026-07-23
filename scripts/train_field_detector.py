"""Reproducible field-detector training (YOLOv8-OBB).

The STNK/KTP detectors were trained by ad-hoc CLI; this makes retraining any
document type a repo-tracked, one-command job — including the new SIM/KIR
detectors trained on synthetic data from scripts/synth_cards.py.

    # 1. build synthetic data (labels are exact, generated with the pixels)
    python scripts/synth_cards.py --type SIM --n 1500 --out ./train_runs/data/sim_synth
    # 2. train
    python scripts/train_field_detector.py --data ./train_runs/data/sim_synth/data.yaml \
        --name sim_fields --epochs 80

Weights land at <project>/<name>/weights/best.pt. Point the pipeline at them:
    FIELD_DETECTOR_SIM_WEIGHTS=./train_runs/sim_fields/weights/best.pt

Matches the STNK run's hyperparameters (yolov8s-obb, imgsz 640, seeded,
deterministic) so results are comparable.
"""
import argparse
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to data.yaml")
    ap.add_argument("--name", required=True, help="run name (e.g. sim_fields)")
    ap.add_argument("--model", default="yolov8s-obb.pt")
    ap.add_argument("--project", default="./train_runs")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="0", help="'0' for GPU, 'cpu' otherwise")
    args = ap.parse_args()

    data = Path(args.data)
    if not data.exists():
        raise SystemExit(f"data.yaml not found: {data}")

    from ultralytics import YOLO
    model = YOLO(args.model)
    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        exist_ok=True,
        seed=0,
        deterministic=True,
        patience=20,
        verbose=False,
        # synthetic cards already carry perspective/lighting variety; keep the
        # geometric aug mild so boxes stay meaningful for OBB
        degrees=0.0, shear=0.0, perspective=0.0, mosaic=1.0, close_mosaic=10,
        fliplr=0.0, flipud=0.0,   # ID text is orientation-specific; don't mirror
    )
    best = Path(args.project) / args.name / "weights" / "best.pt"
    print(f"\nbest weights: {best}")
    print(f"enable with:  FIELD_DETECTOR_{args.name.split('_')[0].upper()}_WEIGHTS={best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
