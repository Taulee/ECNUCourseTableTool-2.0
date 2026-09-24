import subprocess
import unittest
from unittest.mock import patch

from ecnu_calendar import detect_lan_ip


def command_result(output: str, code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, output, "")


class DetectLanIpTests(unittest.TestCase):
    @patch("ecnu_calendar.platform.system", return_value="Darwin")
    @patch("ecnu_calendar.subprocess.run")
    def test_macos_uses_wifi_hardware_port_instead_of_tun(self, run, _system):
        ports = (
            "Hardware Port: Ethernet Adapter (en4)\nDevice: en4\n\n"
            "Hardware Port: Wi-Fi\nDevice: en0\n\n"
            "Hardware Port: Thunderbolt Bridge\nDevice: bridge0\n"
        )
        run.side_effect = [
            command_result(ports),
            command_result("10.0.0.2\n"),
            command_result("192.168.5.9\n"),
        ]

        self.assertEqual(detect_lan_ip(), "192.168.5.9")
        self.assertEqual(run.call_args_list[1].args[0], ["ipconfig", "getifaddr", "en4"])
        self.assertEqual(run.call_args_list[2].args[0], ["ipconfig", "getifaddr", "en0"])

    @patch("ecnu_calendar.platform.system", return_value="Linux")
    @patch("ecnu_calendar.subprocess.run")
    def test_linux_ignores_tun_even_when_it_appears_first(self, run, _system):
        run.return_value = command_result(
            '[{"ifname":"tun0","link_type":"none","addr_info":'
            '[{"family":"inet","scope":"global","local":"198.18.0.1"}]},'
            '{"ifname":"wlan0","link_type":"ether","addr_info":'
            '[{"family":"inet","scope":"global","local":"192.168.1.23"}]}]'
        )

        self.assertEqual(detect_lan_ip(), "192.168.1.23")

    @patch("ecnu_calendar.platform.system", return_value="Windows")
    @patch("ecnu_calendar.subprocess.run")
    def test_windows_uses_physical_adapter(self, run, _system):
        run.return_value = command_result("192.168.1.23\n")

        self.assertEqual(detect_lan_ip(), "192.168.1.23")
        self.assertIn("Get-NetAdapter -Physical", run.call_args.args[0][-1])

    @patch("ecnu_calendar.platform.system", return_value="Darwin")
    @patch("ecnu_calendar.subprocess.run")
    def test_no_active_hardware_address_requests_manual_host(self, run, _system):
        run.return_value = command_result("Hardware Port: Wi-Fi\nDevice: en0\n")
        run.side_effect = [run.return_value, command_result("", 1)]

        with self.assertRaisesRegex(RuntimeError, "--host"):
            detect_lan_ip()


if __name__ == "__main__":
    unittest.main()
