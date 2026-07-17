from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Settings:
    project_root: Path = Path(__file__).resolve().parents[3]
    data_dir: Path = field(default_factory=lambda: Path("data"))


SETTINGS = Settings()
