# SPDX-License-Identifier: MIT
import io

from ..malloc import Heap
from ..utils import *
from ..constructutils import ConstructClassBase, str_value
from construct import Bytes, Container, HexDump

class GPUObject:
    def __init__(self, allocator, objtype):
        if isinstance(objtype, ConstructClassBase):
            self.val = objtype
            objtype = type(objtype)
            self._size = objtype.sizeof()
            self._name = objtype.__name__
        elif isinstance(objtype, type) and issubclass(objtype, ConstructClassBase):
            self._size = objtype.sizeof()
            self.val = objtype()
            self._name = objtype.__name__
        else:
            self._size = objtype.sizeof()
            self.val = objtype.parse(bytes(self._size))
            self._name = type(objtype).__name__

        self._alloc = allocator
        self._type = objtype
        self._addr = None

    def push(self):
        assert self._addr is not None
        stream = self._alloc.make_stream(self._addr)
        context = Container()
        context._parsing = False
        context._building = True
        context._sizing = False
        context._params = context
        print(f"[{self._name} @{self._addr:#x}] pushing {self._size} bytes")

        # build locally and push as a block for efficiency
        ios = io.BytesIO()
        self._type._build(self.val, ios, context, "(pushing)")
        stream.write(ios.getvalue())
        if isinstance(self._type, type) and issubclass(self._type, ConstructClassBase):
            print("setmeta", self._type)
            self.val.set_addr(self._addr, stream)

        return self

    def pull(self):
        assert self._addr is not None
        stream = self._alloc.make_stream(self._addr)
        context = Container()
        context._parsing = True
        context._building = False
        context._sizing = False
        context._params = context
        print(f"[{self._name} @{self._addr:#x}] pulling {self._size} bytes")
        self.val = self._type._parse(stream, context, "(pulling)")

        return self

    def add_to_mon(self, mon):
        ctx = self._alloc.ctx
        mon.add(self._addr, self._size, self._name, offset=0,
                readfn=lambda a, s: self._alloc.agx.uat.ioread(ctx,  a, s))

    def _set_addr(self, addr, paddr=None):
        self._addr = addr
        self._paddr = paddr
        if isinstance(self.val, ConstructClassBase):
            self.val.set_addr(addr)

    def __getitem__(self, item):
        return self.val[item]
    def __setitem__(self, item, value):
        self.val[item] = value

    def __getattr__(self, attr):
        return getattr(self.val, attr)

    def __setattr__(self, attr, val):
        if attr.startswith("_") or attr == "val":
            self.__dict__[attr] = val
            return

        setattr(self.val, attr, val)

    def __str__(self):
        s_val = str_value(self.val)
        return f"GPUObject {self._name} ({self._size:#x} @ {self._addr:#x}): " + s_val

class GPUAllocator:
    def __init__(self, agx, name, start, size,
                 ctx=0, page_size=16384, va_block=None, **kwargs):
        self.page_size = page_size
        if va_block is None:
            va_block = page_size
        self.agx = agx
        self.ctx = ctx
        self.name = name
        self.va = Heap(start, start + size, block=va_block)
        self.verbose = 1
        self.objects = {}
        self.flags = kwargs

    def make_stream(self, base):
        return self.agx.uat.iostream(self.ctx, base)

    def new(self, objtype, name=None, **kwargs):
        obj = GPUObject(self, objtype)
        obj._stream = self.make_stream
        if name is not None:
            obj._name = name

        size_align = align_up(obj._size, self.page_size)
        addr = self.va.malloc(size_align + self.page_size)
        paddr = self.agx.u.memalign(self.page_size, size_align)
        off = size_align - obj._size

        flags = dict(self.flags)
        flags.update(kwargs)

        self.agx.uat.iomap_at(self.ctx, addr, paddr, size_align, **flags)
        obj._set_addr(addr + off, paddr + off)

        self.objects[obj._addr] = obj

        print(f"[{self.name}] Alloc {obj._name} size {obj._size:#x} @ {obj._addr:#x} ({obj._paddr:#x})")

        self.agx.reg_object(obj)
        return obj

    def new_buf(self, size, name):
        return self.new(HexDump(Bytes(size)), name=name).push()

    def buf(self, size, name):
        return self.new_buf(size, name)._addr
