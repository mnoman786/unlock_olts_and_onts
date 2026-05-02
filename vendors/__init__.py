from .huawei import HuaweiVendor
from .zte import ZTEVendor
from .fiberhome import FiberHomeVendor
from .nokia import NokiaVendor
from .calix import CalixVendor
from .generic import GenericVendor

VENDOR_MAP = {
    'huawei': HuaweiVendor,
    'zte': ZTEVendor,
    'fiberhome': FiberHomeVendor,
    'nokia': NokiaVendor,
    'calix': CalixVendor,
    'generic': GenericVendor,
}

def get_vendor(name, connection):
    cls = VENDOR_MAP.get(name, GenericVendor)
    return cls(connection)
