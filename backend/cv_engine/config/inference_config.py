from pathlib import Path


class InferenceConfig:
    MODEL_PATH: str = str(Path("models") / "best.pt")
    CONFIDENCE_THRESHOLD: float = 0.5
    FRAME_SKIP: int = 2
    INPUT_SIZE: int = 640
