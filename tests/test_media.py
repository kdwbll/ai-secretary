from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from email.message import EmailMessage
from unittest.mock import Mock
from unittest.mock import patch
import zipfile

from PIL import Image
from core.secretary.database import Database
from core.secretary.files import FilePipeline
from core.secretary.memory import MemoryEngine
from core.secretary.storage import LocalStorage


class MediaTests(unittest.TestCase):
    def _pipeline(self, root: Path):
        database = Database(root / "data.db")
        memory = MemoryEngine(LocalStorage(root / "memory"), database)
        memory.initialize()
        return FilePipeline(root / "files", database, memory, Mock())

    def test_html_eml_and_pptx_text_are_supported(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline = self._pipeline(root)
            html = root / "notice.html"
            html.write_text("<h1>报名通知</h1><p>截止时间 18:00</p>", encoding="utf-8")
            self.assertIn("截止时间 18:00", pipeline.extract(html))

            eml = root / "notice.eml"
            message = EmailMessage()
            message["Subject"] = "会议"
            message.set_content("会议室改为 302。")
            eml.write_bytes(message.as_bytes())
            self.assertIn("会议室改为 302", pipeline.extract(eml))

            slides = root / "slides.pptx"
            with zipfile.ZipFile(slides, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<root><p>项目里程碑</p><p>十月完成</p></root>")
            self.assertIn("项目里程碑", pipeline.extract(slides))
    def test_legacy_doc_uses_system_text_extractor(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            pipeline = FilePipeline(root / "files", database, memory, Mock())
            source = root / "legacy.doc"
            source.write_bytes(b"fake-old-word")
            completed = subprocess.CompletedProcess([], 0, "旧版 Word 正文".encode("utf-8"), b"")
            with patch("core.secretary.files.shutil.which", return_value="/usr/bin/textutil"), patch("core.secretary.files.subprocess.run", return_value=completed):
                self.assertEqual(pipeline.extract(source), "旧版 Word 正文")

    def test_blank_duplicate_document_is_reanalyzed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            pipeline = FilePipeline(root / "files", database, memory, Mock())
            source = root / "legacy.doc"
            source.write_bytes(b"same-document")
            with patch.object(pipeline, "extract", return_value=""):
                first = pipeline.ingest(source, "legacy.doc")
            with patch.object(pipeline, "extract", return_value="现在可以读取正文"):
                second = pipeline.ingest(source, "legacy.doc")
            self.assertTrue(second["duplicate"])
            self.assertTrue(second["reanalyzed"])
            self.assertEqual(second["extracted_text"], "现在可以读取正文")

    def test_delete_removes_file_and_database_record(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            pipeline = FilePipeline(root / "files", database, memory, Mock())
            source = root / "note.txt"
            source.write_text("需要保存的内容", encoding="utf-8")
            record = pipeline.ingest(source, "note.txt")
            archived = root / record["stored_path"]
            self.assertTrue(archived.is_file())

            pipeline.delete(record["hash"])

            self.assertFalse(archived.exists())
            self.assertEqual(database.rows("SELECT * FROM files WHERE hash=?", (record["hash"],)), [])

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
