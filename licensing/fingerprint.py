"""机器指纹 —— 跨平台、稳定、不含个人信息。

取操作系统自带的机器 ID（重装系统会变，换硬件不一定变），加盐哈希后截断。
拿不到就退回网卡 MAC。指纹只用于把许可绑到设备，不回传任何东西。
"""
import hashlib
import platform
import subprocess
import uuid

SALT = b"edu-shift-scheduling/v1"


def _linux():
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            pass
    return None


def _macos():
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return None


def _windows():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Cryptography")
        try:
            return winreg.QueryValueEx(key, "MachineGuid")[0]
        finally:
            winreg.CloseKey(key)
    except (ImportError, OSError):
        pass
    return None


def raw_machine_id():
    system = platform.system()
    value = {"Linux": _linux, "Darwin": _macos, "Windows": _windows}.get(system, lambda: None)()
    if not value:
        # 兜底：网卡 MAC。虚拟网卡多的机器上可能不稳，所以只当最后一招。
        value = "mac-%012x" % uuid.getnode()
    return "%s/%s" % (system, value)


def machine_fingerprint():
    """返回 16 位十六进制指纹，例如 'a3f1c02e9b4d7185'。"""
    digest = hashlib.sha256(SALT + raw_machine_id().encode("utf-8")).hexdigest()
    return digest[:16]


if __name__ == "__main__":
    print(machine_fingerprint())
