from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path("data"))


SETTINGS = Settings()
