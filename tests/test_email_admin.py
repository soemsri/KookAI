import unittest

from main import get_tunnel_block_page, is_tunnel_allowed_path, is_tunnel_host


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
            "/api/upload-media",
            "/api/usage-limits",
            "/api/media",
            "/api/conversation/abc123",
            "/api/chat-tasks/task123",
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



if __name__ == "__main__":
    unittest.main()
