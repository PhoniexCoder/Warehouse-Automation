from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Settings:
    project_root: Path = Path(__file__).resolve().parents[3]
    models_dir: Path = field(default_factory=lambda: Path("models"))
    data_dir: Path = field(default_factory=lambda: Path("data"))
    videos_dir: Path = field(default_factory=lambda: Path("videos"))

    yolo_model_path: str = "models/yolo11n.pt"
    yolo_confidence_threshold: float = 0.5
    yolo_iou_threshold: float = 0.7
    yolo_device: str = "cpu"
    yolo_classes: list[int] = field(default_factory=lambda: [0])

    line_y_position: int = 400
    line_color: tuple[int, int, int] = (0, 255, 0)
    line_thickness: int = 2

    frame_skip: int = 2
    frame_width: int = 1280
    frame_height: int = 720

    video_source: str = "0"
    rtsp_reconnect_delay: float = 5.0

    database_url: str = "sqlite:///data/detections.db"

    bbox_color: tuple[int, int, int] = (0, 255, 0)
    bbox_thickness: int = 2
    text_color: tuple[int, int, int] = (255, 255, 255)
    text_bg_color: tuple[int, int, int] = (0, 0, 0)
    text_scale: float = 0.6
    text_thickness: int = 1

    display_enabled: bool = True
    display_window_name: str = "Warehouse AI - Box Counter"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False

    counted_history_limit: int = 1000


SETTINGS = Settings()
