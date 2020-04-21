import socket
from dataclasses import fields
from enum import IntEnum
from typing import TypeVar, Type

import netstruct

# Helper structs which maps primitive types to the netstruct format string symbols which should be used to serialize
# those types
format_dict = {
    bool: b'B',
    float: b'f',
    int: b'B', # for now all ints are assumed to be unsigned 8-bit values !!
    str: b'i$'
}

T = TypeVar('T')


def unflatten_from_string(sock: socket.socket, cls: Type[T], includes_size: bool) -> T:
    """
    Unflatten data following the format of LabView's "Flatten to string" vi into a corresponding dataclass instance

    :param sock: socket on which the (possibly variable-length) data is received
    :param cls: type of the dataclass into which data should be deserialized
    :param includes_size: if true, the payload is preceded by a 32-bit signed big-endian integer containing the message length
    :return: dataclass instance
    """

    fmt, names = zip(*[(format_dict[field.type if not issubclass(field.type, IntEnum) else int], field.name) for field in fields(cls)])
    fmt = b''.join(fmt)

    if includes_size:
        data = sock.recv(4)
        sz = netstruct.unpack(b'i', data)
        vals = netstruct.unpack(fmt, sock.recv(sz[0]))
    else:
        unpacker = netstruct.obj_unpack(fmt)
        remain = unpacker.remaining
        while (remain := unpacker.feed(sock.recv(remain))) != 0:
            pass
        vals = unpacker.result
    return cls(**{name: (val.decode('utf-8') if isinstance(val, bytes) else val) for name, val in zip(names, vals)})


def flatten_to_string(obj) -> bytes:
    """
    Flatten a dataclass instance into a binary representation which can be deserialized with LabView's "Unflatten from string" vi.

    :param obj: dataclass instance to flatten
    :return: binary string
    """
    fmt, vals = zip(*[(format_dict[field.type if not isinstance(field.type, IntEnum) else int], getattr(obj, field.name)) for field in fields(obj)])
    vals = [val.encode('utf-8') if isinstance(val, str) else val for val in vals]
    res = netstruct.pack(b''.join(fmt), *vals)
    return res