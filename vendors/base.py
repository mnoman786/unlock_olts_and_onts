from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class ONTInfo:
    serial_number: str
    ont_id: str
    port: str
    slot: str = '0'
    frame: str = '0'
    status: str = 'unknown'
    description: str = ''
    raw_line: str = ''

    def port_label(self):
        return f"{self.frame}/{self.slot}/{self.port}"

    def __str__(self):
        desc = f"  [{self.description}]" if self.description else ''
        return (f"SN: {self.serial_number:<20} "
                f"Port: {self.port_label():<12} "
                f"ID: {self.ont_id:<6} "
                f"Status: {self.status}{desc}")


class BaseVendor(ABC):
    NAME = 'Base'

    def __init__(self, connection):
        self.conn = connection

    def enter_privileged_mode(self, enable_password=None):
        """Override if vendor requires enable/config mode before commands."""
        pass

    @abstractmethod
    def get_all_onts(self) -> List[ONTInfo]:
        """Return list of all registered ONTs/ONUs on this OLT."""

    @abstractmethod
    def delete_ont(self, ont: ONTInfo) -> bool:
        """
        Remove/deprovision the ONT so it can register on another OLT.
        Returns True if the command was sent successfully.
        """

    def reset_ont(self, ont: 'ONTInfo') -> bool:
        """
        Send OMCI factory-reset command to the ONT through the OLT.
        ONT will reboot and lose all pushed OMCI config.
        Returns True if command was accepted.
        """
        return False

    def save_config(self):
        """Persist changes.  Override per vendor."""
        pass

    def _send(self, cmd, wait=2.0):
        return self.conn.send(cmd, wait=wait)
