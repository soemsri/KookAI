import os
import tempfile
import unittest
from unittest import mock

import main


class ProjectDiscoveryTests(unittest.TestCase):
    def test_lists_only_directories_from_configured_roots(self):
        with tempfile.TemporaryDirectory() as projects_root:
            os.mkdir(os.path.join(projects_root, "agy-mobile"))
            os.mkdir(os.path.join(projects_root, "VirtualOffice"))
            os.mkdir(os.path.join(projects_root, ".hidden"))
            with open(os.path.join(projects_root, "README.txt"), "w", encoding="utf-8"):
                pass

            with mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                self.assertEqual(
                    main.get_desktop_projects(),
                    ["agy-mobile", "VirtualOffice"],
                )

    def test_does_not_add_hard_coded_or_app_sibling_projects(self):
        with (
            tempfile.TemporaryDirectory() as projects_root,
            tempfile.TemporaryDirectory() as releases_root,
        ):
            os.mkdir(os.path.join(projects_root, "real-project"))
            os.mkdir(os.path.join(releases_root, "release-id"))

            with (
                mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                mock.patch.object(
                    main, "APP_DIR", os.path.join(releases_root, "current-release")
                ),
            ):
                self.assertEqual(main.get_desktop_projects(), ["real-project"])

    def test_resolves_only_projects_in_configured_roots(self):
        with (
            tempfile.TemporaryDirectory() as projects_root,
            tempfile.TemporaryDirectory() as releases_root,
        ):
            expected = os.path.join(projects_root, "real-project")
            os.mkdir(expected)
            os.mkdir(os.path.join(releases_root, "release-id"))

            with (
                mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                mock.patch.object(
                    main, "APP_DIR", os.path.join(releases_root, "current-release")
                ),
            ):
                self.assertEqual(
                    main.resolve_project_directory("real-project"),
                    expected,
                )
                with self.assertRaises(ValueError):
                    main.resolve_project_directory("release-id")
                with self.assertRaises(ValueError):
                    main.resolve_project_directory("../real-project")

    def test_preserves_legacy_ginraidee_display_name_mapping(self):
        with tempfile.TemporaryDirectory() as projects_root:
            expected = os.path.join(projects_root, "GinRaiD")
            os.mkdir(expected)

            with mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                self.assertEqual(main.get_desktop_projects(), ["GinRaiDee"])
                self.assertEqual(
                    main.resolve_project_directory("GinRaiDee"),
                    expected,
                )

    def test_creates_project_in_first_configured_root(self):
        with (
            tempfile.TemporaryDirectory() as primary_root,
            tempfile.TemporaryDirectory() as secondary_root,
        ):
            with mock.patch.object(
                main,
                "PROJECTS_ROOTS",
                (primary_root, secondary_root),
            ):
                project, project_path = main.create_project_directory("แอปใหม่")

                self.assertEqual(project, "แอปใหม่")
                self.assertEqual(project_path, os.path.join(primary_root, "แอปใหม่"))
                self.assertTrue(os.path.isdir(project_path))
                self.assertFalse(
                    os.path.exists(os.path.join(secondary_root, "แอปใหม่"))
                )

    def test_rejects_duplicate_project_names_case_insensitively(self):
        with tempfile.TemporaryDirectory() as projects_root:
            os.mkdir(os.path.join(projects_root, "Existing"))

            with mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                with self.assertRaises(FileExistsError):
                    main.create_project_directory("existing")

    def test_rejects_unsafe_or_nonportable_project_names(self):
        invalid_names = [
            "",
            "   ",
            ".hidden",
            "..",
            "../escape",
            r"..\escape",
            "bad:name",
            "trailing.",
            "CON",
            "control\x00name",
        ]

        with tempfile.TemporaryDirectory() as projects_root:
            with mock.patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                for name in invalid_names:
                    with self.subTest(name=name):
                        with self.assertRaises(ValueError):
                            main.create_project_directory(name)


if __name__ == "__main__":
    unittest.main()
