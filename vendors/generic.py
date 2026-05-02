import re
from typing import List
from .base import BaseVendor, ONTInfo


# Common "show all ONTs" commands tried in order
DISCOVERY_COMMANDS = [
    ('display ont info 0 all',              'huawei_table'),
    ('display ont info summary',            'huawei_table'),
    ('show gpon onu state',                 'zte_table'),
    ('show pon onu-state',                  'zte_table'),
    ('show ont autofind all',               'fh_table'),
    ('show equipment ont summary',          'nokia_table'),
    ('show ont summary',                    'generic_table'),
    ('show gpon ont-info all',              'generic_table'),
    ('show onu info all',                   'generic_table'),
]


class GenericVendor(BaseVendor):
    NAME = 'Generic (auto-probe)'

    def enter_privileged_mode(self, enable_password=None):
        # Try common enable sequences
        out = self._send('enable', wait=1.0)
        if re.search(r'[Pp]assword', out) and enable_password:
            self._send(enable_password, wait=1.0)
        # Try entering config mode
        self._send('config', wait=1.0)

    # ---------------------------------------------------------------- discover

    def get_all_onts(self) -> List[ONTInfo]:
        for cmd, fmt in DISCOVERY_COMMANDS:
            out = self._send(cmd, wait=4.0)
            onts = self._parse(out, fmt)
            if onts:
                return onts
        return []

    def _parse(self, text: str, fmt: str) -> List[ONTInfo]:
        if fmt == 'huawei_table':
            return self._parse_huawei(text)
        if fmt == 'zte_table':
            return self._parse_zte(text)
        if fmt == 'fh_table':
            return self._parse_fh(text)
        if fmt == 'nokia_table':
            return self._parse_nokia(text)
        return self._parse_generic(text)

    def _parse_huawei(self, text: str) -> List[ONTInfo]:
        onts = []
        p = re.compile(
            r'(\d+)/\s*(\d+)/\s*(\d+)\s+(\d+)\s+([0-9A-Za-z\-]{8,20})\s+\S+\s+(\S+)'
        )
        for m in p.finditer(text):
            frame, slot, port, ont_id, sn, status = m.groups()
            onts.append(ONTInfo(serial_number=sn, ont_id=ont_id, port=port,
                                slot=slot, frame=frame, status=status))
        return onts

    def _parse_zte(self, text: str) -> List[ONTInfo]:
        onts = []
        p = re.compile(
            r'(?:gpon-olt_)?(\d+)/(\d+)/(\d+)\s+(\d+)\s+([0-9A-Za-z:]{4,20})\s+(\S+)'
        )
        for m in p.finditer(text):
            rack, slot, port, onu_id, sn, status = m.groups()
            onts.append(ONTInfo(serial_number=sn, ont_id=onu_id, port=port,
                                slot=slot, frame=rack, status=status))
        return onts

    def _parse_fh(self, text: str) -> List[ONTInfo]:
        onts = []
        p = re.compile(r'(\d+)\s+(\d+)\s+(\d+)\s+([0-9A-Za-z]{8,20})\s+(\S+)')
        for m in p.finditer(text):
            slot, port, onu_id, sn, status = m.groups()
            onts.append(ONTInfo(serial_number=sn, ont_id=onu_id, port=port,
                                slot=slot, frame='0', status=status))
        return onts

    def _parse_nokia(self, text: str) -> List[ONTInfo]:
        onts = []
        p = re.compile(
            r'(\d+)/(\d+)/(\d+)/(\d+)\s+\S+\s+(\S+)\s+([0-9A-Za-z]{8,20})'
        )
        for m in p.finditer(text):
            rack, shelf, slot, ont_id, status, sn = m.groups()
            onts.append(ONTInfo(serial_number=sn, ont_id=ont_id, port=slot,
                                slot=shelf, frame=rack, status=status))
        return onts

    def _parse_generic(self, text: str) -> List[ONTInfo]:
        """
        Last-resort: look for anything that looks like a serial number
        (8-16 hex chars or vendor-prefixed strings) on lines with port-like patterns.
        """
        onts = []
        p = re.compile(
            r'(\d+)[/\s]+(\d+)[/\s]+(\d+)\s+'
            r'(\d+)\s+'
            r'([0-9A-Fa-f]{8,20})'
        )
        for m in p.finditer(text):
            f, s, port, oid, sn = m.groups()
            onts.append(ONTInfo(serial_number=sn, ont_id=oid, port=port,
                                slot=s, frame=f, status='?'))
        return onts

    # ----------------------------------------------------------------- delete

    # Delete command templates tried in order; {f}=frame {s}=slot {p}=port {id}=ont_id {sn}=serial
    DELETE_TEMPLATES = [
        # Huawei style (requires entering interface first via separate send)
        ('interface gpon {f}/{s}',
         'ont delete {p} {id}',
         'quit'),
        # ZTE style
        (None,
         'no pon onu-authorized gpon-olt_{f}/{s}/{p} sn {sn}',
         None),
        # FiberHome style
        (None,
         'no ont-port slot {s} pon {p} onu {id}',
         None),
        # Nokia style
        (None,
         'configure no equipment ont {f}/{s}/{p}/{id}',
         None),
        # Generic undo by SN
        (None,
         'undo ont add {f}/{s}/{p} sn {sn}',
         None),
    ]

    def delete_ont(self, ont: ONTInfo) -> bool:
        ctx = dict(f=ont.frame, s=ont.slot, p=ont.port,
                   id=ont.ont_id, sn=ont.serial_number)
        for pre, cmd, post in self.DELETE_TEMPLATES:
            if pre:
                self._send(pre.format(**ctx), wait=1.0)
            out = self._send(cmd.format(**ctx), wait=2.0)
            if post:
                self._send(post.format(**ctx), wait=1.0)
            if not re.search(r'[Ee]rror|[Uu]nknown command|[Ii]nvalid', out):
                return True
        return False

    RESET_TEMPLATES = [
        ('interface gpon {f}/{s}',       'ont restore-factory {p} {id}', 'quit'),
        ('interface gpon {f}/{s}',       'ont reset {p} {id}',           'quit'),
        (None, 'pon onu reset gpon-olt_{f}/{s}/{p} onu_id {id}',         None),
        (None, 'ont factory-reset slot {s} pon {p} onu {id}',            None),
        (None, 'configure equipment ont {f}/{s}/{p}/{id} reset',          None),
    ]

    def reset_ont(self, ont: ONTInfo) -> bool:
        ctx = dict(f=ont.frame, s=ont.slot, p=ont.port,
                   id=ont.ont_id, sn=ont.serial_number)
        for pre, cmd, post in self.RESET_TEMPLATES:
            if pre:
                self._send(pre.format(**ctx), wait=1.0)
            out = self._send(cmd.format(**ctx), wait=5.0)
            if post:
                self._send(post.format(**ctx), wait=1.0)
            if not re.search(r'[Ee]rror|[Uu]nknown command|[Ii]nvalid', out):
                return True
        return False

    def save_config(self):
        for cmd in ('save', 'write', 'commit', 'copy running startup'):
            out = self._send(cmd, wait=3.0)
            if re.search(r'[Yy]/[Nn]|\[y\]|[Cc]onfirm', out):
                self._send('y', wait=3.0)
            if not re.search(r'[Uu]nknown command|[Ii]nvalid', out):
                break
