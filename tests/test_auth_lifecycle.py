import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from publisher import state, sync


class CredentialCheckpointTests(unittest.TestCase):
    def test_unchanged_state_does_not_create_an_encrypted_commit(self):
        payload = {"app_id": "app", "credentials": {"config": "old"}}
        publisher = sync.Publisher(payload, "sha")
        with patch(
            "publisher.state.capture_credentials", return_value={"config": "old"}
        ), patch("publisher.state.save") as save:
            publisher.persist()
        save.assert_not_called()

    def test_refreshed_credentials_are_saved_before_response_decoding(self):
        publisher = sync.Publisher(
            {"app_id": "app", "credentials": {"config": "old"}}, "sha"
        )
        with patch("publisher.sync.run", return_value="invalid json"), patch(
            "publisher.state.capture_credentials", return_value={"config": "rotated"}
        ), patch("publisher.state.save", return_value="next") as save:
            with self.assertRaises(ValueError):
                publisher.api("+get")
        self.assertEqual(save.call_args.args[0]["credentials"], {"config": "rotated"})
        self.assertEqual(publisher.sha, "next")

    def test_failed_request_still_checkpoints_a_refresh(self):
        publisher = sync.Publisher(
            {"app_id": "app", "credentials": {"config": "old"}}, "sha"
        )
        failure = sync.ExternalOperationError(
            "Network failed", "private transport failure"
        )
        with patch("publisher.sync.run", side_effect=failure), patch(
            "publisher.state.capture_credentials", return_value={"config": "rotated"}
        ), patch("publisher.state.save", return_value="next") as save:
            with self.assertRaises(sync.ExternalOperationError):
                publisher.api("+get")
        save.assert_called_once()
        self.assertEqual(save.call_args.args[0]["credentials"]["config"], "rotated")

    def test_failed_checkpoint_remains_retryable_and_uses_latest_sha(self):
        payload = {"app_id": "app", "credentials": {"config": "old"}}
        publisher = sync.Publisher(payload, "sha")
        with patch(
            "publisher.state.capture_credentials", return_value={"config": "new"}
        ), patch(
            "publisher.state.save",
            side_effect=[RuntimeError("transport"), "next", "last"],
        ) as save:
            with self.assertRaises(RuntimeError):
                publisher.persist()
            publisher.persist()
            payload["pending"] = {"release_id": "release"}
            publisher.persist()
        self.assertEqual(
            [call.args[1] for call in save.call_args_list], ["sha", "sha", "next"]
        )


class AuthorizationPollTests(unittest.TestCase):
    def setUp(self):
        setting = patch.dict(os.environ, {"PUBLISHER_HOME": "/isolated/publisher-test"})
        setting.start()
        self.addCleanup(setting.stop)

    def test_idle_poll_checks_authorization_without_creating_a_release(self):
        payload = {
            "app_id": "app",
            "credentials": {"config": "stored"},
            "published_sources": ["source"],
            "dashboard_revision": "current",
        }
        events = []

        def command(args, **kwargs):
            events.append(args)
            return '{"ok":true,"data":{}}'

        with patch("publisher.state.load", return_value=(payload, "sha")), patch(
            "publisher.state.restore_credentials"
        ), patch(
            "publisher.state.capture_credentials", return_value=payload["credentials"]
        ), patch(
            "publisher.state.save"
        ) as save, patch(
            "publisher.sync.run", side_effect=command
        ), patch(
            "publisher.source.available",
            side_effect=lambda: events.append("source") or [],
        ), patch(
            "publisher.sync.collect", return_value=([], [])
        ), patch(
            "publisher.sync.dashboard_revision", return_value="current"
        ), patch.object(
            sync.Publisher, "publish"
        ) as publish:
            sync.main()
        self.assertEqual(events[0][:3], ["lark-cli", "apps", "+get"])
        self.assertEqual(events[1][:3], ["lark-cli", "auth", "check"])
        self.assertEqual(events[2], "source")
        self.assertIn("offline_access", events[1][events[1].index("--scope") + 1])
        save.assert_not_called()
        publish.assert_not_called()

    def test_missing_authorization_stops_before_fetching_or_publishing(self):
        payload = {"app_id": "app", "credentials": {"config": "stored"}}
        failure = sync.ExternalOperationError(
            "CLI failed", '{"error":{"code":"token_missing"}}'
        )
        with patch("publisher.state.load", return_value=(payload, "sha")), patch(
            "publisher.state.restore_credentials"
        ), patch(
            "publisher.state.capture_credentials", return_value=payload["credentials"]
        ), patch(
            "publisher.state.save", return_value="next"
        ), patch(
            "publisher.sync.run", side_effect=failure
        ), patch(
            "publisher.source.available"
        ) as source, patch.object(
            sync.Publisher, "publish"
        ) as publish:
            with self.assertRaisesRegex(RuntimeError, "authorization"):
                sync.main()
        source.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(payload["diagnostic"]["type"], "AuthorizationRequiredError")


class IsolatedCredentialTests(unittest.TestCase):
    def test_cli_home_and_state_storage_use_the_same_isolated_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"config": "e30=", "master.key": "a2V5", "user.enc": "dG9rZW4="}
            personal = Path(tmp) / "personal/.lark-cli/config.json"
            personal.parent.mkdir(parents=True)
            personal.write_text("personal config sentinel")
            with patch.dict(os.environ, {"PUBLISHER_HOME": tmp}), patch(
                "publisher.state.Path.home", return_value=Path(tmp) / "personal"
            ):
                state.restore_credentials(payload)
                self.assertEqual(state.capture_credentials(), payload)
                with patch(
                    "publisher.sync.subprocess.run",
                    return_value=Mock(returncode=0, stdout="", stderr=""),
                ) as run:
                    sync.run(["lark-cli", "auth", "status"])
                env = run.call_args.kwargs["env"]
                self.assertEqual(env["HOME"], tmp)
                self.assertEqual(env["XDG_DATA_HOME"], str(Path(tmp) / ".local/share"))
                self.assertEqual(env["XDG_CONFIG_HOME"], str(Path(tmp) / ".config"))
                self.assertNotIn("STATE_KEY", env)
            self.assertTrue((Path(tmp) / ".lark-cli/config.json").is_file())
            self.assertEqual(personal.read_text(), "personal config sentinel")


class AuthorizationErrorTests(unittest.TestCase):
    def setUp(self):
        setting = patch.dict(os.environ, {"PUBLISHER_HOME": "/isolated/publisher-test"})
        setting.start()
        self.addCleanup(setting.stop)

    def test_scope_check_errors_require_consent_but_transport_errors_do_not(self):
        for detail in (
            '{"ok":false,"missing":["offline_access"]}',
            '{"ok":false,"error":"no_token"}',
            '{"error":{"code":"token_missing"}}',
        ):
            with self.subTest(detail=detail):
                self.assertTrue(
                    sync.authorization_required(
                        sync.ExternalOperationError("failed", detail)
                    )
                )
        self.assertFalse(
            sync.authorization_required(
                sync.ExternalOperationError("failed", "HTTP 503")
            )
        )

    def test_idle_poll_retries_a_transient_failure_on_the_next_invocation(self):
        payload = {
            "app_id": "app",
            "credentials": {"config": "stored"},
            "published_sources": ["source"],
            "dashboard_revision": "current",
        }
        failure = sync.ExternalOperationError("Network failed", "HTTP 503")
        with patch("publisher.state.load", side_effect=lambda: (payload, "sha")), patch(
            "publisher.state.restore_credentials"
        ), patch(
            "publisher.state.capture_credentials", return_value=payload["credentials"]
        ), patch(
            "publisher.state.save", return_value="next"
        ), patch(
            "publisher.sync.run",
            side_effect=[failure, '{"ok":true,"data":{}}', '{"ok":true}'],
        ), patch(
            "publisher.source.available", return_value=[]
        ), patch(
            "publisher.sync.collect", return_value=([], [])
        ), patch(
            "publisher.sync.dashboard_revision", return_value="current"
        ):
            with self.assertRaises(sync.ExternalOperationError):
                sync.main()
            self.assertIn("diagnostic", payload)
            sync.main()
        self.assertNotIn("diagnostic", payload)


class IsolationGuardTests(unittest.TestCase):
    def test_sync_requires_an_explicit_isolated_home_before_loading_state(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "publisher.state.load"
        ) as load:
            with self.assertRaisesRegex(RuntimeError, "PUBLISHER_HOME"):
                sync.main()
        load.assert_not_called()

    def test_personal_home_is_rejected_before_restoring_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PUBLISHER_HOME": tmp}), patch(
                "publisher.state.Path.home", return_value=Path(tmp)
            ), patch("publisher.state.load") as load:
                with self.assertRaisesRegex(RuntimeError, "personal home"):
                    sync.main()
            load.assert_not_called()
