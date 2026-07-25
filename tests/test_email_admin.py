import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

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

    def test_verify_google_auth_rejects_manual_identity(self):
        with self.assertRaises(ValidationError):
            GoogleAuthVerifyRequest(
                email="attacker@example.com",
                name="Attacker"
            )

    def test_verify_google_auth_rejects_unverified_token(self):
        config = load_google_auth_config()
        config["client_id"] = "test-client.apps.googleusercontent.com"
        save_google_auth_config(config)

        with patch(
            "main.google_id_token.verify_oauth2_token",
            side_effect=ValueError("Invalid token"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    verify_google_auth(
                        GoogleAuthVerifyRequest(credential="forged.token.value")
                    )
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_verify_google_auth_accepts_verified_google_token(self):
        config = load_google_auth_config()
        config["client_id"] = "test-client.apps.googleusercontent.com"
        config["admin_email"] = "owner@example.com"
        save_google_auth_config(config)
        verified_claims = {
            "iss": "https://accounts.google.com",
            "aud": config["client_id"],
            "sub": "google-subject-123",
            "email": "owner@example.com",
            "email_verified": True,
            "name": "Owner",
            "picture": "",
        }

        with (
            patch(
                "main.google_id_token.verify_oauth2_token",
                return_value=verified_claims,
            ) as verify_token,
            patch("main.save_google_auth_session") as save_session,
        ):
            response = asyncio.run(
                verify_google_auth(
                    GoogleAuthVerifyRequest(credential="valid-google-id-token")
                )
            )

        self.assertEqual(response.status_code, 200)
        user = json.loads(response.body)["user"]
        self.assertTrue(user["is_admin"])
        verify_token.assert_called_once()
        self.assertEqual(verify_token.call_args.args[2], config["client_id"])
        save_session.assert_called_once()

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
