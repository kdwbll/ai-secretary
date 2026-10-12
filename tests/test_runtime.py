from unittest import TestCase

from core.secretary.runtime import ServiceRuntime


class ServiceRuntimeTests(TestCase):
    def test_pause_and_resume_change_the_exposed_state(self):
        runtime = ServiceRuntime()
        self.assertEqual(runtime.status("0.8.0", True)["state"], "running")
        runtime.pause()
        self.assertTrue(runtime.paused)
        self.assertEqual(runtime.status("0.8.0", True)["state"], "paused")
        runtime.resume()
        self.assertFalse(runtime.paused)
        self.assertEqual(runtime.status("0.8.0", False), {"state": "running", "version": "0.8.0", "can_control": False})
