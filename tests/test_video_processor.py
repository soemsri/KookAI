import unittest
import tempfile
from pathlib import Path
from video_processor import (
    is_url,
    is_video_source,
    parse_time,
    format_time,
    parse_vtt,
    format_transcript,
    dedupe_perceptual,
    load_whisper_key,
)

class TestVideoProcessor(unittest.TestCase):

    def test_url_detection(self):
        self.assertTrue(is_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_url("http://vimeo.com/123456"))
        self.assertFalse(is_url("/local/path/video.mp4"))
        self.assertFalse(is_url("C:\\videos\\clip.mov"))

    def test_video_source_detection(self):
        self.assertTrue(is_video_source("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_video_source("https://www.tiktok.com/@user/video/123"))
        self.assertFalse(is_video_source("https://example.com/index.html"))
        
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            self.assertTrue(is_video_source(tmp.name))

    def test_time_parsing_and_formatting(self):
        self.assertEqual(parse_time("30"), 30.0)
        self.assertEqual(parse_time("01:30"), 90.0)
        self.assertEqual(parse_time("01:02:03"), 3723.0)
        self.assertIsNone(parse_time(None))
        
        self.assertEqual(format_time(90), "01:30")
        self.assertEqual(format_time(3723), "1:02:03")

    def test_vtt_parsing(self):
        vtt_content = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello and welcome to this video.

00:00:04.000 --> 00:00:07.000
Hello and welcome to this video.

00:00:07.000 --> 00:00:10.000
Today we are demonstrating KookAI.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vtt_path = Path(tmpdir) / "test.vtt"
            vtt_path.write_text(vtt_content, encoding="utf-8")
            
            segments = parse_vtt(str(vtt_path))
            self.assertEqual(len(segments), 2)  # Rolling duplicate collapsed
            self.assertEqual(segments[0]["text"], "Hello and welcome to this video.")
            self.assertEqual(segments[0]["end"], 7.0)
            
            formatted = format_transcript(segments)
            self.assertIn("[00:01] Hello and welcome to this video.", formatted)
            self.assertIn("[00:07] Today we are demonstrating KookAI.", formatted)

    def test_dedupe_perceptual_fallback(self):
        candidates = [
            {"index": 0, "path": "/fake/frame_0001.jpg", "timestamp_seconds": 0.0},
            {"index": 1, "path": "/fake/frame_0002.jpg", "timestamp_seconds": 1.0},
        ]
        # Since ffmpeg thumbnailing won't find /fake files, dedupe returns unchanged list
        kept, dropped = dedupe_perceptual(candidates)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 0)

    def test_extract_video_target(self):
        from video_processor import extract_video_target
        self.assertIsNone(extract_video_target("/watch สวัสดี"))
        self.assertIsNone(extract_video_target("/watch help"))
        self.assertEqual(
            extract_video_target("/watch https://youtu.be/dQw4w9WgXcQ เกิดอะไรขึ้น?"),
            "https://youtu.be/dQw4w9WgXcQ"
        )
        self.assertEqual(
            extract_video_target("/watch", attached_media=["/tmp/test.mp4"]),
            "/tmp/test.mp4"
        )

    def test_multi_key_whisper_rotation(self):
        import os
        from unittest.mock import patch
        from video_processor import load_all_whisper_keys, load_whisper_key, parse_key_candidates

        self.assertEqual(parse_key_candidates("key1, key2\nkey3"), ["key1", "key2", "key3"])

        mock_env = {
            **os.environ,
            "GROQ_API_KEYS": "gsk_test1, gsk_test2",
            "GROQ_API_KEY": "",
            "OPENAI_API_KEY": "",
            "OPENAI_API_KEYS": "",
        }
        with patch.dict(os.environ, mock_env), \
             patch("pathlib.Path.exists", return_value=False):
            keys = load_all_whisper_keys("groq")
            self.assertEqual(len(keys), 2)
            self.assertEqual(keys[0], ("groq", "gsk_test1"))
            self.assertEqual(keys[1], ("groq", "gsk_test2"))

            # Test round-robin
            k1 = load_whisper_key("groq")
            k2 = load_whisper_key("groq")
            k3 = load_whisper_key("groq")
            self.assertEqual(k1, ("groq", "gsk_test1"))
            self.assertEqual(k2, ("groq", "gsk_test2"))
            self.assertEqual(k3, ("groq", "gsk_test1"))

    def test_transcribe_key_failover(self):
        import os
        from unittest.mock import patch
        from video_processor import transcribe_video_audio

        mock_env = {
            **os.environ,
            "GROQ_API_KEYS": "bad_key1, good_key2",
            "GROQ_API_KEY": "",
            "OPENAI_API_KEY": "",
            "OPENAI_API_KEYS": "",
        }
        with patch.dict(os.environ, mock_env), \
             patch("shutil.which", return_value="ffmpeg"), \
             patch("video_processor.load_all_whisper_keys", return_value=[("groq", "bad_key1"), ("groq", "good_key2")]), \
             patch("subprocess.run") as mock_sub, \
             patch("video_processor._post_whisper_multipart") as mock_post:
            
            mock_sub.return_value.returncode = 0
            
            # First key fails, second key succeeds
            mock_post.side_effect = [
                Exception("429 Rate Limit Exceeded"),
                {"segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}]}
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                audio_file = Path(tmpdir) / "audio.mp3"
                audio_file.write_bytes(b"dummy mp3 data")

                segments, backend = transcribe_video_audio("/fake/video.mp4", Path(tmpdir))
                self.assertEqual(backend, "groq")
                self.assertEqual(len(segments), 1)
                self.assertEqual(segments[0]["text"], "Hello world")
                self.assertEqual(mock_post.call_count, 2)

if __name__ == "__main__":
    unittest.main()
