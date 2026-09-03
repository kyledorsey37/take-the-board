#!/usr/bin/env python3
"""Safe, dependency-free regression checks for the hosted dev env contract."""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/dev/docker-compose.yml"
APP_ENV_EXAMPLE = ROOT / "deploy/dev/env.example"
POSTGRES_ENV_EXAMPLE = ROOT / "deploy/dev/postgres.env.example"
REMOTE_DEPLOY = ROOT / "deploy/dev/remote_deploy.sh"


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:|^volumes:)",
        compose,
    )
    if not match:
        raise AssertionError(f"service {service!r} is missing")
    return match.group(1)


def env_keys(path: pathlib.Path) -> list[str]:
    keys = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, _ = line.partition("=")
        if not separator:
            raise AssertionError(f"invalid env example line in {path}: {line!r}")
        keys.append(key)
    return keys


class DevDeploymentContractTests(unittest.TestCase):
    def test_compose_assigns_only_the_dedicated_file_to_postgres(self) -> None:
        compose = COMPOSE.read_text()
        web = service_block(compose, "web")
        worker = service_block(compose, "worker")
        postgres = service_block(compose, "postgres")

        self.assertIn("- ${TAKEBOARD_ENV_FILE:-.env}", web)
        self.assertIn("- ${TAKEBOARD_ENV_FILE:-.env}", worker)
        self.assertIn("- ${TAKEBOARD_POSTGRES_ENV_FILE:-.postgres.env}", postgres)
        self.assertNotIn("TAKEBOARD_ENV_FILE", postgres)
        self.assertEqual(postgres.count("env_file:"), 1)
        self.assertIn("postgres_data:/var/lib/postgresql/data", postgres)

        remote_deploy = REMOTE_DEPLOY.read_text()
        self.assertNotIn("docker compose down", remote_deploy)
        self.assertNotIn("docker volume", remote_deploy)

        deploy_script = (ROOT / "deploy/dev/deploy_dev.sh").read_text()
        self.assertIn('exec env TTB_APPLICATION_ENV_FILE="\\${application_env_file}"', deploy_script)

    def test_postgres_example_has_exactly_the_three_allowed_keys(self) -> None:
        self.assertEqual(
            env_keys(POSTGRES_ENV_EXAMPLE),
            ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"],
        )
        self.assertEqual(
            set(key for key in env_keys(POSTGRES_ENV_EXAMPLE) if key.startswith("POSTGRES_")),
            {"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"},
        )

    def test_application_example_uses_database_url_without_postgres_container_keys(self) -> None:
        app_keys = env_keys(APP_ENV_EXAMPLE)
        self.assertIn("DATABASE_URL", app_keys)
        self.assertIn("TAKEBOARD_ENV_FILE", app_keys)
        self.assertIn("TAKEBOARD_POSTGRES_ENV_FILE", app_keys)
        self.assertFalse(any(key.startswith("POSTGRES_") for key in app_keys))

    def test_remote_migration_creates_and_validates_split_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deployment_dir = pathlib.Path(directory)
            app_env = deployment_dir / ".env"
            app_env.write_text(
                "TAKEBOARD_IMAGE=example/image:tag\n"
                "TAKEBOARD_POSTGRES_ENV_FILE=.postgres.env\n"
                "DATABASE_URL=postgres://ttb:placeholder-password@postgres:5432/ttb\n"
                "POSTGRES_DB=ttb\n"
                "POSTGRES_USER=ttb\n"
                "POSTGRES_PASSWORD=placeholder-password\n"
            )
            app_env.chmod(0o644)

            result = subprocess.run(
                ["bash", str(REMOTE_DEPLOY), "ignored-image-reference"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "TTB_DEPLOYMENT_DIR": str(deployment_dir),
                    "TTB_VALIDATE_DEPLOYMENT_ENV_ONLY": "1",
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                env_keys(deployment_dir / ".postgres.env"),
                ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"],
            )
            self.assertNotRegex(app_env.read_text(), r"(?m)^POSTGRES_(?:DB|USER|PASSWORD)=")
            self.assertEqual((deployment_dir / ".env").stat().st_mode & 0o777, 0o600)
            self.assertEqual((deployment_dir / ".postgres.env").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("placeholder-password", result.stdout + result.stderr)

    def test_remote_migration_rejects_malformed_dedicated_file_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deployment_dir = pathlib.Path(directory)
            (deployment_dir / ".env").write_text(
                "TAKEBOARD_IMAGE=example/image:tag\n"
                "TAKEBOARD_POSTGRES_ENV_FILE=.postgres.env\n"
            )
            (deployment_dir / ".postgres.env").write_text(
                "POSTGRES_DB=ttb\nPOSTGRES_USER=ttb\nUNEXPECTED=value\n"
            )

            result = subprocess.run(
                ["bash", str(REMOTE_DEPLOY), "ignored-image-reference"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "TTB_DEPLOYMENT_DIR": str(deployment_dir),
                    "TTB_VALIDATE_DEPLOYMENT_ENV_ONLY": "1",
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must contain exactly one non-empty", result.stderr)
            self.assertNotIn("UNEXPECTED=value", result.stdout + result.stderr)

    def test_remote_migration_rejects_missing_or_conflicting_legacy_credentials(self) -> None:
        for legacy_content, expected_error in (
            (
                "TAKEBOARD_IMAGE=example/image:tag\nTAKEBOARD_POSTGRES_ENV_FILE=.postgres.env\n",
                "must contain non-empty POSTGRES_DB",
            ),
            (
                "TAKEBOARD_IMAGE=example/image:tag\n"
                "TAKEBOARD_POSTGRES_ENV_FILE=.postgres.env\n"
                "POSTGRES_DB=other\nPOSTGRES_USER=ttb\nPOSTGRES_PASSWORD=placeholder-password\n",
                "do not match",
            ),
        ):
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as directory:
                deployment_dir = pathlib.Path(directory)
                (deployment_dir / ".env").write_text(legacy_content)
                if "do not match" in expected_error:
                    (deployment_dir / ".postgres.env").write_text(
                        "POSTGRES_DB=ttb\nPOSTGRES_USER=ttb\nPOSTGRES_PASSWORD=placeholder-password\n"
                    )

                result = subprocess.run(
                    ["bash", str(REMOTE_DEPLOY), "ignored-image-reference"],
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "TTB_DEPLOYMENT_DIR": str(deployment_dir),
                        "TTB_VALIDATE_DEPLOYMENT_ENV_ONLY": "1",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertNotIn("placeholder-password", result.stdout + result.stderr)

    def test_deployment_scripts_are_valid_bash_and_reports_are_redacted(self) -> None:
        for path in (ROOT / "deploy/dev/deploy_dev.sh", REMOTE_DEPLOY):
            result = subprocess.run(["bash", "-n", str(path)], check=False)
            self.assertEqual(result.returncode, 0, str(path))

        deploy_script = (ROOT / "deploy/dev/deploy_dev.sh").read_text()
        self.assertNotIn("StandardOutputContent", deploy_script)
        self.assertNotIn("StandardErrorContent", deploy_script)


if __name__ == "__main__":
    unittest.main()
