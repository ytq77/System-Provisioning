import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stream_routing import StreamRouter, live_stream, register_routing_api, validate_destination
from monitor_rtmp import RTMPMonitor


class FakeProcess:
    def __init__(self):
        self.stdout = io.StringIO("")
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.status = {"active": True, "stream_key": "live_test", "last_update": time.time()}
        self.factory = Mock(side_effect=lambda *args, **kwargs: FakeProcess())
        self.path = Path(self.tmp.name) / "settings.json"
        self.router = StreamRouter(self.path, lambda: self.status, "rtmp://ps5living:1935/app", self.factory)
        self.addCleanup(self.router.close)

    def direct(self):
        self.router.save("direct", "rtmp://example.com/live/key?token=secret&x=1")
        self.router.tick()

    def test_obs_default_never_forwards(self):
        self.router.tick()
        self.factory.assert_not_called()
        self.assertEqual(self.router.snapshot()["state"], "obs")

    def test_switch_to_obs_stops_existing_forwarder(self):
        self.direct()
        old = self.router.proc
        command = self.factory.call_args.args[0]
        self.assertIn("rtmp://ps5living:1935/app/live_test", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertFalse(self.factory.call_args.kwargs["shell"])
        self.router.save("obs")
        self.router.tick()
        self.assertTrue(old.terminated)
        self.assertIsNone(self.router.proc)
        self.assertEqual(self.router.snapshot()["state"], "obs")
        self.router.save("direct")
        self.router.tick()
        self.assertEqual(self.factory.call_count, 2)

    def test_no_duplicate_process_and_url_change_stops_old(self):
        self.direct()
        old = self.router.proc
        self.router.tick()
        self.router.save("direct")
        self.router.tick()
        self.assertEqual(self.factory.call_count, 1)
        self.router.save("direct", "rtmps://new.example/live/newkey")
        self.router.tick()
        self.assertTrue(old.terminated)
        self.assertEqual(self.factory.call_count, 2)

    def test_ps5_stream_key_change_restarts_forwarder(self):
        self.direct()
        old = self.router.proc
        self.status["stream_key"] = "live_new"
        self.router.tick()
        self.assertTrue(old.terminated)
        self.assertIn("rtmp://ps5living:1935/app/live_new", self.factory.call_args.args[0])

    def test_stale_monitor_stops_forwarder_and_recovers(self):
        self.direct()
        old = self.router.proc
        self.status["last_update"] = time.time() - 30
        self.router.tick()
        self.assertTrue(old.terminated)
        self.assertEqual(self.router.snapshot()["state"], "waiting")
        self.assertEqual(self.router.snapshot()["stream_key"], "")
        self.status["last_update"] = time.time()
        self.router.tick()
        self.assertEqual(self.factory.call_count, 2)

    def test_failed_process_obeys_retry_delay(self):
        self.direct()
        self.router.proc.returncode = 1
        self.router.tick()
        self.assertEqual(self.router.snapshot()["state"], "error")
        self.router.tick()
        self.router.tick()
        self.assertEqual(self.factory.call_count, 1)
        self.router.retry_at = 0
        self.router.tick()
        self.assertEqual(self.factory.call_count, 2)

    def test_missing_ffmpeg_does_not_claim_forwarding(self):
        self.factory.side_effect = FileNotFoundError
        self.direct()
        self.assertEqual(self.router.snapshot()["state"], "error")
        self.router.tick()
        self.assertEqual(self.factory.call_count, 1)

    def test_hung_process_killed_before_obs_applied(self):
        self.direct()
        old = self.router.proc
        old.wait = Mock(side_effect=[subprocess.TimeoutExpired("ffmpeg", 3), 0])
        self.router.save("obs")
        self.router.tick()
        self.assertTrue(old.killed)
        self.assertEqual(self.router.snapshot()["state"], "obs")

    def test_no_progress_retries_without_duplicate(self):
        self.direct()
        old = self.router.proc
        self.router.started_at = time.monotonic() - 40
        self.router.tick()
        self.assertTrue(old.terminated)
        self.assertEqual(self.router.snapshot()["state"], "error")
        self.router.tick()
        self.assertEqual(self.factory.call_count, 1)

    def test_persistence_and_credentials_not_returned(self):
        self.direct()
        recovered = StreamRouter(self.path, lambda: self.status, "rtmp://localhost/app")
        self.assertEqual(recovered.config["mode"], "direct")
        self.assertIn("token=secret", recovered.config["direct_url"])
        self.assertNotIn("secret", json.dumps(recovered.snapshot()))
        self.router.save("obs")
        self.assertTrue(self.router.snapshot()["direct_url_configured"])

    def test_invalid_and_unwritable_settings_leave_current_mode(self):
        for value in ("http://example.com/a", "rtmp://", "rtmp://example.com/a\nmalicious", "rtmp://a:bad/b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.router.save("direct", value)
        self.assertFalse(self.path.exists())
        with patch.object(Path, "replace", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                self.router.save("direct", "rtmp://example.com/live/key")
        self.assertEqual(self.router.config["mode"], "obs")
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_obs_switch_ignores_unfinished_destination_edit(self):
        self.direct()
        self.router.save("obs", "not a URL yet")
        self.router.tick()
        self.assertEqual(self.router.snapshot()["state"], "obs")

    def test_api_validates_requests_and_keeps_key_private(self):
        app = Flask(__name__)
        register_routing_api(app, self.router)
        client = app.test_client()
        self.assertEqual(client.post('/api/stream-routing', json=[]).status_code, 400)
        self.assertEqual(client.post('/api/stream-routing', json={"mode": "direct"}).status_code, 400)
        self.assertEqual(client.post('/api/stream-routing', json={"mode": "obs"},
                                     headers={"Origin": "https://external.example"}).status_code, 403)
        response = client.post('/api/stream-routing', json={"mode": "direct", "direct_url": "rtmp://example.com/live/secret"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json['state'], 'pending')
        self.assertNotIn('secret', response.text)
        self.router.tick()
        self.assertEqual(client.get('/api/stream-routing').json['state'], 'connecting')
        self.assertEqual(client.get('/api/stream-routing').headers['Cache-Control'], 'no-store')

    def test_real_child_is_stopped_on_mode_change(self):
        def spawn(command, **kwargs):
            return subprocess.Popen([sys.executable, '-u', '-c',
                'import time; print("progress=continue", flush=True); time.sleep(30)'], **kwargs)
        self.router.popen = spawn
        self.direct()
        child = self.router.proc
        deadline = time.monotonic() + 5
        while not self.router.progress_at and time.monotonic() < deadline:
            time.sleep(.02)
        self.router.tick()
        self.assertEqual(self.router.snapshot()['state'], 'forwarding')
        self.router.save('obs')
        self.router.tick()
        self.assertIsNotNone(child.poll())
        self.assertEqual(self.router.snapshot()['state'], 'obs')


class MonitorTests(unittest.TestCase):
    def test_selects_publishing_stream_not_idle_obs_subscription(self):
        xml = '''<rtmp><server><application><name>app</name><live>
        <stream><name>old</name><active/></stream>
        <stream><name>current</name><publishing/><active/><bw_in>5000000</bw_in>
        <meta><video><frame_rate>59.94</frame_rate></video></meta></stream>
        </live></application></server></rtmp>'''
        monitor = RTMPMonitor('http://localhost', 'http://localhost/update')
        with patch('monitor_rtmp.requests.get', return_value=Mock(status_code=200, text=xml)):
            result = monitor.get_rtmp_status()
        self.assertTrue(result['active'])
        self.assertEqual(result['stream_key'], 'current')
        self.assertEqual(result['fps'], 59)
        with patch('monitor_rtmp.requests.get', return_value=Mock(status_code=200, text=xml.replace('<publishing/>', ''))):
            self.assertFalse(monitor.get_rtmp_status()['active'])

    def test_stale_status_never_produces_obs_url(self):
        self.assertEqual(live_stream({'active': True, 'stream_key': 'old', 'last_update': 1}, now=100), '')


if __name__ == '__main__':
    unittest.main()
