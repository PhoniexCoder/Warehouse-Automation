import urllib.request
from pathlib import Path

videos_dir = Path("videos")
videos_dir.mkdir(parents=True, exist_ok=True)

url = "https://github.com/ultralytics/ultralytics/raw/main/examples/tutorial.ipynb"
print("Downloading sample video (this may take a moment)...")

urllib.request.urlretrieve(
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/face-demographics-walking.mp4",
    str(videos_dir / "sample.mp4"),
)
print(f"Sample video saved to {videos_dir / 'sample.mp4'}")
