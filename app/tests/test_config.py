import unittest

import config


class CameraIpTest(unittest.TestCase):
    def test_from_status_url(self):
        cam = {
            "status_url": "http://192.168.1.50/cgi-bin/get_configs.sh?conf=camera",
            "rtsp_main": "rtsp://10.0.0.1/ch0_0.h264",
        }
        self.assertEqual(config.camera_ip(cam), "192.168.1.50")

    def test_fallback_to_rtsp(self):
        self.assertEqual(config.camera_ip({"rtsp_main": "rtsp://192.168.1.51/ch0_0.h264"}), "192.168.1.51")

    def test_none(self):
        self.assertIsNone(config.camera_ip({"name": "x"}))


if __name__ == "__main__":
    unittest.main()
