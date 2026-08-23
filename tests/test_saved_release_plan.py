import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aws" / "verify_saved_release_plan.py"
SPEC = importlib.util.spec_from_file_location("verify_saved_release_plan", SCRIPT)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def plan_for(
    actions: list[str],
    resource_type: str = "aws_service_discovery_service",
    address: str = 'aws_service_discovery_service.service["authentication-service"]',
) -> dict:
    return {
        "resource_changes": [
            {
                "address": address,
                "type": resource_type,
                "change": {"actions": actions},
            }
        ]
    }


class SavedReleasePlanTest(unittest.TestCase):
    def test_allows_cloud_map_create_update_and_noop(self) -> None:
        for actions in (["create"], ["update"], ["no-op"]):
            with self.subTest(actions=actions):
                VERIFIER.verify_no_cloud_map_service_destruction(plan_for(actions))

    def test_rejects_cloud_map_delete_and_replacement(self) -> None:
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(
                    VERIFIER.SavedReleasePlanError,
                    "Cloud Map namespace/service deletion or replacement requires reviewed manual cleanup",
                ):
                    VERIFIER.verify_no_cloud_map_service_destruction(plan_for(actions))

    def test_rejects_private_namespace_deletion(self) -> None:
        with self.assertRaisesRegex(
            VERIFIER.SavedReleasePlanError,
            "Cloud Map namespace/service deletion or replacement requires reviewed manual cleanup",
        ):
            VERIFIER.verify_no_cloud_map_service_destruction(
                plan_for(
                    ["delete"],
                    "aws_service_discovery_private_dns_namespace",
                    "aws_service_discovery_private_dns_namespace.main",
                )
            )

    def test_does_not_broaden_the_guard_to_unrelated_resources(self) -> None:
        VERIFIER.verify_no_cloud_map_service_destruction(plan_for(["delete", "create"], "aws_launch_template"))

    def test_rejects_missing_or_malformed_change_inventory(self) -> None:
        for malformed in ({}, {"resource_changes": [None]}, {"resource_changes": [{}]}):
            with self.subTest(plan=malformed):
                with self.assertRaises(VERIFIER.SavedReleasePlanError):
                    VERIFIER.verify_no_cloud_map_service_destruction(malformed)


if __name__ == "__main__":
    unittest.main()
