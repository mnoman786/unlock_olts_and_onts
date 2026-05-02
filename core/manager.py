from typing import List, Optional
from .connector import OLTConnection
from .detector import probe_vendor
from vendors import get_vendor
from vendors.base import ONTInfo


class OLTManager:
    def __init__(self):
        self.connection: Optional[OLTConnection] = None
        self.vendor = None
        self.vendor_name: str = ''
        self.vendor_key: str = ''

    # ------------------------------------------------------------ connection

    def connect(self, host: str, port: int, username: str, password: str,
                protocol: str, enable_password: str = '') -> str:
        """Connect to OLT and return the login banner."""
        self.connection = OLTConnection(
            host=host,
            port=port,
            username=username,
            password=password,
            protocol=protocol,
            enable_password=enable_password,
        )
        banner = self.connection.connect()
        return banner

    def detect_vendor(self):
        """Auto-detect vendor; returns (key, display_name)."""
        key, name = probe_vendor(self.connection)
        self.vendor_key = key
        self.vendor_name = name
        self.vendor = get_vendor(key, self.connection)
        return key, name

    def set_vendor_manually(self, key: str):
        self.vendor_key = key
        self.vendor = get_vendor(key, self.connection)
        from vendors import VENDOR_MAP
        cls = VENDOR_MAP.get(key)
        self.vendor_name = cls.NAME if cls else key

    def enter_privileged(self, enable_password: str = ''):
        if self.vendor:
            self.vendor.enter_privileged_mode(enable_password or None)

    # -------------------------------------------------------------- operations

    def list_onts(self) -> List[ONTInfo]:
        if not self.vendor:
            raise RuntimeError("Vendor not detected. Call detect_vendor() first.")
        return self.vendor.get_all_onts()

    def delete_ont(self, ont: ONTInfo) -> bool:
        return self.vendor.delete_ont(ont)

    def reset_ont(self, ont: ONTInfo) -> bool:
        return self.vendor.reset_ont(ont)

    def delete_onts(self, onts: List[ONTInfo]) -> dict:
        results = {}
        for ont in onts:
            ok = self.vendor.delete_ont(ont)
            results[ont.serial_number] = ok
        return results

    def save(self):
        if self.vendor:
            self.vendor.save_config()

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def send_raw(self, command: str) -> str:
        """Send a raw command and return output (for manual/debug use)."""
        return self.connection.send(command, wait=2.0)
