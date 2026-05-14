import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock, patch

# Mock subprocess.run to simulate ADB responses
def make_mock_run(responses: dict):
    def mock_run(cmd, **kwargs):
        cmd_str = ' '.join(cmd)
        for key, value in responses.items():
            if key in cmd_str:
                result = MagicMock()
                result.stdout = value
                result.returncode = 0
                return result
        result = MagicMock()
        result.stdout = ""
        result.returncode = 0
        return result
    return mock_run

responses = {
    "adb devices": "List of devices attached\nABC123\tdevice\n",
    "getprop ro.product.model": "Pixel 7\n",
    "getprop ro.product.manufacturer": "Google\n",
    "getprop ro.build.version.release": "14\n",
    "getprop ro.build.version.sdk": "34\n",
    "getprop ro.crypto.state": "encrypted\n",
    "getprop ro.crypto.type": "file\n",
    "getprop ro.hardware.keystore": "default\n",
    "su -c 'id'": "uid=0(root) gid=0(root) groups=0(root)\n",
    "readlink -f /dev/block/by-name/userdata": "/dev/block/sda32\n",
    "readlink -f /dev/block/by-name/metadata": "/dev/block/sda10\n",
}

with patch('subprocess.run', side_effect=make_mock_run(responses)):
    from android.adb_device import AndroidDevice, detect_android_devices

    devices = detect_android_devices()
    print(f"Detected devices: {devices}")

    device = AndroidDevice("ABC123")
    info = device.get_full_info()
    print(f"Model: {info.model}")
    print(f"Rooted: {info.is_rooted}")
    print(f"Storage: {info.storage_type}")
    print(f"TEE-backed: {info.tee_backed_keys}")
    print(f"Available methods: {info.available_wipe_methods}")
