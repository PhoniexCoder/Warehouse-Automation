from pathlib import Path
from ultralytics import YOLO

models_dir = Path("models")
models_dir.mkdir(parents=True, exist_ok=True)

model = YOLO("yolo11n.pt")
model_path = models_dir / "yolo11n.pt"
model.save(str(model_path))
print(f"Model saved to {model_path.resolve()}")
