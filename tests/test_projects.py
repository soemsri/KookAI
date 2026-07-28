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


if __name__ == "__main__":
    unittest.main()
