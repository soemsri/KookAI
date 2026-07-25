import asyncio
import json
import os
import sys
import unittest

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import (
    load_google_auth_config,
    save_google_auth_config,
    is_admin_email,
    get_google_auth_config,
    update_google_auth_config,
    verify_google_auth,
    get_admin_email,
    update_admin_email,
    get_admin_status,
    GoogleAuthConfigRequest,
    GoogleAuthVerifyRequest,
    AdminEmailRequest,
)

class TestEmailAdmin(unittest.TestCase):
    def setUp(self):
        # Backup existing config
        self.orig_config = load_google_auth_config()

    def tearDown(self):
        # Restore original config
        save_google_auth_config(self.orig_config)

    def test_load_and_save_admin_email(self):
        config = load_google_auth_config()
        self.assertIn("admin_email", config)

        test_email = "testadmin@kookai.ai"
        config["admin_email"] = test_email
        save_google_auth_config(config)

        reloaded = load_google_auth_config()
        self.assertEqual(reloaded.get("admin_email"), test_email)

    def test_is_admin_email_logic(self):
        config = load_google_auth_config()
        config["admin_email"] = "admin@kookai.ai, owner@kookai.ai"
        save_google_auth_config(config)

        self.assertTrue(is_admin_email("admin@kookai.ai"))
        self.assertTrue(is_admin_email("ADMIN@KOOKAI.AI "))
        self.assertTrue(is_admin_email("owner@kookai.ai"))
        self.assertFalse(is_admin_email("regular.user@gmail.com"))
        self.assertFalse(is_admin_email(""))
        self.assertFalse(is_admin_email(None))

    def test_verify_google_auth_assigns_admin_role(self):
        config = load_google_auth_config()
        config["admin_email"] = "superuser@domain.com"
        save_google_auth_config(config)

        # 1. Login as Admin user
        req_admin = GoogleAuthVerifyRequest(
            email="superuser@domain.com",
            name="Super Admin"
        )
        res_admin = asyncio.run(verify_google_auth(req_admin))
        self.assertEqual(res_admin.status_code, 200)
        data_admin = json.loads(res_admin.body)
        self.assertTrue(data_admin["user"]["is_admin"])
        self.assertEqual(data_admin["user"]["role"], "admin")

        # 2. Login as Standard user
        req_user = GoogleAuthVerifyRequest(
            email="standard@domain.com",
            name="Standard User"
        )
        res_user = asyncio.run(verify_google_auth(req_user))
        self.assertEqual(res_user.status_code, 200)
        data_user = json.loads(res_user.body)
        self.assertFalse(data_user["user"]["is_admin"])
        self.assertEqual(data_user["user"]["role"], "user")

    def test_admin_email_endpoints(self):
        # GET /api/admin/email
        get_res = asyncio.run(get_admin_email())
        self.assertEqual(get_res.status_code, 200)
        self.assertIn("admin_email", json.loads(get_res.body))

        # POST /api/admin/email
        new_admin = "newadmin@domain.org"
        post_res = asyncio.run(update_admin_email(AdminEmailRequest(admin_email=new_admin)))
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(json.loads(post_res.body)["admin_email"], new_admin)

        # GET /api/admin/status
        status_res = asyncio.run(get_admin_status())
        self.assertEqual(status_res.status_code, 200)
        status_data = json.loads(status_res.body)
        self.assertEqual(status_data["admin_email"], new_admin)

if __name__ == "__main__":
    unittest.main()
