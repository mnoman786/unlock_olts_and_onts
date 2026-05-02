import re
from typing import List
from .base import BaseVendor, ONTInfo


class FiberHomeVendor(BaseVendor):
    NAME = 'FiberHome'

    def enter_privileged_mode(self, enable_password=None):
        out = self._send('enable', wait=1.0)
        if re.search(r'[Pp]assword', out) and enable_password:
            self._send(enable_password, wait=1.0)

    # ---------------------------------------------------------------- discover

    def get_all_onts(self) -> List[ONTInfo]:
        onts: List[ONTInfo] = []

        # AN5516 command
        out = self._send('show ont autofind all', wait=5.0)
        parsed = self._parse_autofind(out)
        if parsed:
            return parsed

        # Alternate: show onu state all
        out = self._send('show onu state all', wait=5.0)
        parsed = self._parse_onu_state(out)
        if parsed:
            return parsed

        # Per-port brute force
        for slot in range(1, 9):
            for port in range(1, 17):
                out = self._send(f'show ont info slot {slot} pon {port}', wait=3.0)
                onts.extend(self._parse_ont_info(out, str(slot), str(port)))

        return onts

    def _parse_autofind(self, text: str) -> List[ONTInfo]:
        """
        FiberHome autofind format:
          Slot  PON  ONU-ID  SN            Status
          3     1    1       FHTT12345678  online
        """
        onts = []
        pattern = re.compile(
            r'(\d+)\s+(\d+)\s+(\d+)\s+([0-9A-Za-z]{8,20})\s+(\S+)'
        )
        for m in pattern.finditer(text):
            slot, port, onu_id, sn, status = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=onu_id,
                port=port,
                slot=slot,
                frame='0',
                status=status,
                raw_line=m.group(0),
            ))
        return onts

    def _parse_onu_state(self, text: str) -> List[ONTInfo]:
        return self._parse_autofind(text)

    def _parse_ont_info(self, text: str, slot: str, port: str) -> List[ONTInfo]:
        onts = []
        pattern = re.compile(r'(\d+)\s+([0-9A-Za-z]{8,20})\s+(\S+)')
        for m in pattern.finditer(text):
            onu_id, sn, status = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=onu_id,
                port=port,
                slot=slot,
                frame='0',
                status=status,
            ))
        return onts

    # ----------------------------------------------------------------- delete

    def delete_ont(self, ont: ONTInfo) -> bool:
        # FiberHome AN5516 style
        out = self._send(
            f'no ont-port slot {ont.slot} pon {ont.port} onu {ont.ont_id}',
            wait=2.0,
        )
        if re.search(r'[Ee]rror|[Ii]nvalid', out):
            # Alternative command form
            out = self._send(
                f'undo ont add slot {ont.slot} pon {ont.port} sn {ont.serial_number}',
                wait=2.0,
            )
        return True

    def reset_ont(self, ont: ONTInfo) -> bool:
        out = self._send(
            f'ont factory-reset slot {ont.slot} pon {ont.port} onu {ont.ont_id}',
            wait=5.0,
        )
        if re.search(r'[Ee]rror|[Ii]nvalid', out):
            out = self._send(
                f'ont reset slot {ont.slot} pon {ont.port} onu {ont.ont_id}',
                wait=5.0,
            )
        return not bool(re.search(r'[Ee]rror|[Ff]ail', out))

    def save_config(self):
        out = self._send('save', wait=3.0)
        if re.search(r'[Yy]/[Nn]|\[y\]', out):
            self._send('y', wait=3.0)
