from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import Mock

from PIL import Image
from core.secretary.database import Database
from core.secretary.files import FilePipeline
from core.secretary.memory import MemoryEngine
from core.secretary.storage import LocalStorage


class MediaTests(unittest.TestCase):
    def test_failed_duplicate_is_automatically_reanalyzed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            models = Mock()
            models.route.return_value = object()
            models.analyze_images.side_effect = RuntimeError("错误模型")
            pipeline = FilePipeline(root / "files", database, memory, models)
            image = root / "receipt.png"
            Image.new("RGB", (32, 32), "white").save(image)
            first = pipeline.ingest(image, "receipt.png")
            self.assertIn("模型分析失败", first["extracted_text"])
            models.analyze_images.side_effect = None
            models.analyze_images.return_value = "识别成功：金额 20 元"
            second = pipeline.ingest(image, "receipt.png")
            self.assertTrue(second["duplicate"])
            self.assertTrue(second["reanalyzed"])
            self.assertEqual(second["extracted_text"], "识别成功：金额 20 元")

    def test_video_keyframes_are_extracted(self):
        try:
            import imageio_ffmpeg
        except ImportError:
            self.skipTest("imageio-ffmpeg is not installed")
        with TemporaryDirectory() as temp:
            video = Path(temp) / "sample.mp4"
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1", "-pix_fmt", "yuv420p", str(video),
            ], check=True, timeout=30)
            frames = FilePipeline._video_frames(video)
            try:
                self.assertGreaterEqual(len(frames), 1)
                self.assertTrue(frames[0].is_file())
            finally:
                import shutil
                shutil.rmtree(frames[0].parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
