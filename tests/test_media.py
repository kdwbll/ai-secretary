from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from core.secretary.files import FilePipeline


class MediaTests(unittest.TestCase):
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
