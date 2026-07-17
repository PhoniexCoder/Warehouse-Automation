from pathlib import Path


class InferenceConfig:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
    _CANDIDATES = [
        _PROJECT_ROOT / "models" / "box_model.pt",
        _PROJECT_ROOT / "backend" / "models" / "box_model.pt",
        Path.cwd() / "models" / "box_model.pt",
    ]
    MODEL_PATH: str = str(
        next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])
    )
    CONFIDENCE_THRESHOLD: float = 0.5
    FRAME_SKIP: int = 2
    INPUT_SIZE: int = 640
