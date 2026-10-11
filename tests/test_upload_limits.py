import asyncio
from io import BytesIO
from unittest import TestCase

from fastapi import HTTPException, UploadFile

from core.secretary.app import save_upload_to_temp


class UploadLimitTests(TestCase):
    def test_upload_over_limit_is_rejected_before_processing(self):
        upload = UploadFile(filename="large.bin", file=BytesIO(b"123456"))
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(save_upload_to_temp(upload, ".bin", limit_bytes=5))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertIn("上传上限", raised.exception.detail)

    def test_upload_at_limit_is_saved(self):
        upload = UploadFile(filename="small.txt", file=BytesIO(b"12345"))
        path = asyncio.run(save_upload_to_temp(upload, ".txt", limit_bytes=5))
        try:
            self.assertEqual(path.read_bytes(), b"12345")
        finally:
            path.unlink(missing_ok=True)
