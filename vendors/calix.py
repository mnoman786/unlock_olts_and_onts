import re
from typing import List
from .base import BaseVendor, ONTInfo


class CalixVendor(BaseVendor):
    NAME = 'Calix'

    def enter_privileged_mode(self, enable_password=None):
        out = self._send('enable', wait=1.0)
        if re.search(r'[Pp]assword', out) and enable_password:
            self._send(enable_password, wait=1.0)

    # ---------------------------------------------------------------- discover

    def get_all_onts(self) -> List[ONTInfo]:
        out = self._send('show ont summary', wait=5.0)
        onts = self._parse_ont_summary(out)
        if not onts:
            out = self._send('show gpon ont-info all', wait=5.0)
            onts = self._parse_ont_summary(out)
        return onts

    def _parse_ont_summary(self, text: str) -> List[ONTInfo]:
        """
        Calix E7 example:
          Shelf/Slot/Port/ONT   SN              State
          1/1/gp1/1             CXNK0012ABCD    operational
        """
        onts = []
        # Format: shelf/slot/portname/ont_id  SN  state
        pattern = re.compile(
            r'(\d+)/(\d+)/\S+/(\d+)\s+'
            r'([0-9A-Za-z]{8,20})\s+'
            r'(\S+)'
        )
        for m in pattern.finditer(text):
            shelf, slot, ont_id, sn, status = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=ont_id,
                port='0',
                slot=slot,
                frame=shelf,
                status=status,
                raw_line=m.group(0),
            ))
        return onts

    # ----------------------------------------------------------------- delete

    def delete_ont(self, ont: ONTInfo) -> bool:
        out = self._send(f'no ont sn {ont.serial_number}', wait=2.0)
        if re.search(r'[Ee]rror|[Ii]nvalid', out):
            out = self._send(
                f'configure no equipment ont {ont.frame}/{ont.slot}/1/{ont.ont_id}',
                wait=2.0,
            )
        return True

    def save_config(self):
        out = self._send('commit', wait=3.0)
        if re.search(r'[Yy]/[Nn]', out):
            self._send('y', wait=3.0)
