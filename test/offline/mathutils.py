"""Pure-Python stand-in for Blender's mathutils (Vector only).

Used by the offline test harness (no Blender available): test scripts put
test/offline/ first on sys.path so `from mathutils import Vector` inside the
addon modules resolves here. Implements exactly the Vector surface the addon
uses: arithmetic, dot/cross, length(_squared), normalized/normalize, angle,
copy, iteration and x/y/z accessors. Inside Blender the real mathutils wins.
"""

import math


class Vector:
    __slots__ = ("_v",)

    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self._v = [float(c) for c in seq]

    # --- components -------------------------------------------------------
    @property
    def x(self):
        return self._v[0]

    @x.setter
    def x(self, val):
        self._v[0] = float(val)

    @property
    def y(self):
        return self._v[1]

    @y.setter
    def y(self, val):
        self._v[1] = float(val)

    @property
    def z(self):
        return self._v[2]

    @z.setter
    def z(self, val):
        self._v[2] = float(val)

    def __getitem__(self, i):
        return self._v[i]

    def __setitem__(self, i, val):
        self._v[i] = float(val)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def copy(self):
        return Vector(self._v)

    # --- arithmetic -------------------------------------------------------
    def __add__(self, other):
        return Vector([a + b for a, b in zip(self._v, other)])

    def __iadd__(self, other):
        self._v = [a + b for a, b in zip(self._v, other)]
        return self

    def __sub__(self, other):
        return Vector([a - b for a, b in zip(self._v, other)])

    def __isub__(self, other):
        self._v = [a - b for a, b in zip(self._v, other)]
        return self

    def __mul__(self, s):
        return Vector([a * s for a in self._v])

    __rmul__ = __mul__

    def __truediv__(self, s):
        return Vector([a / s for a in self._v])

    def __itruediv__(self, s):
        self._v = [a / s for a in self._v]
        return self

    def __neg__(self):
        return Vector([-a for a in self._v])

    def __eq__(self, other):
        try:
            return list(self._v) == [float(c) for c in other]
        except TypeError:
            return NotImplemented

    def __repr__(self):
        return "Vector((" + ", ".join(f"{c:.4f}" for c in self._v) + "))"

    # --- metrics ----------------------------------------------------------
    @property
    def length(self):
        return math.sqrt(sum(c * c for c in self._v))

    @property
    def length_squared(self):
        return sum(c * c for c in self._v)

    def dot(self, other):
        return sum(a * b for a, b in zip(self._v, other))

    def cross(self, other):
        a, b = self._v, [float(c) for c in other]
        return Vector((
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ))

    def normalized(self):
        l = self.length
        if l < 1e-12:
            return Vector((0.0, 0.0, 0.0))
        return Vector([c / l for c in self._v])

    def normalize(self):
        l = self.length
        if l >= 1e-12:
            self._v = [c / l for c in self._v]
        return self

    def angle(self, other):
        d = self.dot(other) / (self.length * Vector(list(other)).length)
        return math.acos(max(-1.0, min(1.0, d)))
