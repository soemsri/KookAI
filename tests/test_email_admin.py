import os
import tempfile
import unittest
import urllib.parse

from main import (
    get_tunnel_block_page,
    is_allowed_media_path,
    is_tunnel_allowed_path,
    is_tunnel_host,
    rewrite_local_media_links,
)


class TunnelAccessPolicyTests(unittest.TestCase):
    def test_tunnel_host_detection(self):
        self.assertTrue(is_tunnel_host("example.trycloudflare.com"))
        self.assertTrue(is_tunnel_host("example.trycloudflare.com:443"))
        self.assertFalse(is_tunnel_host("localhost:8080"))
        self.assertFalse(is_tunnel_host("127.0.0.1:8080"))

    def test_tunnel_allows_only_mobile_api_paths(self):
        allowed_paths = [
            "/api/pair",
            "/api/models",
            "/api/projects",
            "/api/chat-history",
            "/api/chat",
            "/api/chat-tasks",
            "/api/chat-tasks/cancel",
            "/api/upload-media",
            "/api/usage-limits",
            "/api/media",
            "/api/media/generated-video.mp4",
            "/api/conversation/abc123",
            "/api/chat-tasks/task123",
            "/api/chat-tasks/task123/cancel",
        ]
        for path in allowed_paths:
            with self.subTest(path=path):
                self.assertTrue(is_tunnel_allowed_path(path))

        blocked_paths = [
            "/",
            "/index.html",
            "/script.js",
            "/style.css",
            "/pair.html",
            "/api/pairing-code",
            "/api/admin/status",
        ]
        for path in blocked_paths:
            with self.subTest(path=path):
                self.assertFalse(is_tunnel_allowed_path(path))

    def test_block_page_is_silent_icon_only(self):
        body = get_tunnel_block_page()
        self.assertIn('data:image/png;base64', body)
        self.assertIn('<img ', body)
        self.assertNotIn('KookAI web client', body)
        self.assertNotIn('localhost', body.lower())
        self.assertNotIn('mobile app', body.lower())
        self.assertNotIn('cloudflare', body.lower())

    def test_media_path_is_limited_to_local_allowed_roots(self):
        self.assertIsNotNone(is_allowed_media_path("static/favicon.png"))
        self.assertIsNone(is_allowed_media_path("/etc/passwd"))

    def test_local_markdown_media_links_use_authenticated_media_endpoint(self):
        absolute_path = is_allowed_media_path("static/favicon.png")
        self.assertIsNotNone(absolute_path)

        rewritten = rewrite_local_media_links(
            f"![Generated image]({absolute_path})\n[Open image](<{absolute_path}>)"
        )

        expected_path = urllib.parse.quote(absolute_path, safe="")
        expected_prefix = f"/api/media/favicon.png?path={expected_path}"
        self.assertEqual(rewritten.count(expected_prefix), 2)
        self.assertNotIn(absolute_path, rewritten)

    def test_local_video_file_uri_uses_authenticated_media_endpoint(self):
        with tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".mp4") as video:
            absolute_path = os.path.realpath(video.name)
            rewritten = rewrite_local_media_links(
                f"![Generated video](file://{absolute_path})"
            )

        expected_path = urllib.parse.quote(absolute_path, safe="")
        self.assertEqual(
            rewritten,
            f"![Generated video](/api/media/{os.path.basename(absolute_path)}?path={expected_path})",
        )

    def test_saved_extensionless_media_link_is_upgraded(self):
        with tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".mp4") as video:
            absolute_path = os.path.realpath(video.name)
            encoded_path = urllib.parse.quote(absolute_path, safe="")
            rewritten = rewrite_local_media_links(
                f"![Generated video](/api/media?path={encoded_path})"
            )

        self.assertEqual(
            rewritten,
            f"![Generated video](/api/media/{os.path.basename(absolute_path)}?path={encoded_path})",
        )



if __name__ == "__main__":
    unittest.main()
