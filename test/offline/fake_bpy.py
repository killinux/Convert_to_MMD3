"""Minimal fake `bpy` + mesh layer — lets the REAL weight modules run offline.

install() injects a fake `bpy` module into sys.modules, then the addon's
convert.weights.* files import and execute unmodified: skinned_meshes() sees
bpy.data.objects, operators subclass bpy.types.Operator, vertex groups behave
like Blender's (including index reshuffling on remove, which the weight code
implicitly relies on).

Only the surface the weight pipeline actually touches is implemented.
"""

import sys
import types

from mathutils import Vector


class IdentityMatrix:
    """Stands in for Object.matrix_world (we test in armature==world space)."""

    def __matmul__(self, v):
        return Vector(tuple(v))


# ---------------------------------------------------------------------------
# vertices / vertex groups
# ---------------------------------------------------------------------------

class FakeVGEntry:
    __slots__ = ("group", "weight")

    def __init__(self, group, weight):
        self.group = group
        self.weight = weight


class FakeVertex:
    __slots__ = ("index", "co", "groups")

    def __init__(self, index, co):
        self.index = index
        self.co = Vector(co)
        self.groups = []


class FakeVertexGroup:
    def __init__(self, mesh_obj, name, index):
        self._mesh = mesh_obj
        self.name = name
        self.index = index

    def add(self, indices, weight, mode):
        for i in indices:
            v = self._mesh.data.vertices[i]
            entry = next((e for e in v.groups if e.group == self.index), None)
            if mode == 'REPLACE':
                if entry:
                    entry.weight = weight
                else:
                    v.groups.append(FakeVGEntry(self.index, weight))
            elif mode == 'ADD':
                if entry:
                    entry.weight += weight
                else:
                    v.groups.append(FakeVGEntry(self.index, weight))
            else:
                raise ValueError(mode)

    def remove(self, indices):
        for i in indices:
            v = self._mesh.data.vertices[i]
            v.groups = [e for e in v.groups if e.group != self.index]


class FakeVertexGroups:
    def __init__(self, mesh_obj):
        self._mesh = mesh_obj
        self._list = []

    def new(self, name=""):
        vg = FakeVertexGroup(self._mesh, name, len(self._list))
        self._list.append(vg)
        return vg

    def get(self, name, default=None):
        return next((g for g in self._list if g.name == name), default)

    def remove(self, vg):
        """Blender semantics: deletes the group, strips its entries from all
        vertices, and reindexes the higher groups (entries follow)."""
        idx = vg.index
        for v in self._mesh.data.vertices:
            v.groups = [e for e in v.groups if e.group != idx]
            for e in v.groups:
                if e.group > idx:
                    e.group -= 1
        self._list.remove(vg)
        for g in self._list:
            if g.index > idx:
                g.index -= 1

    def __contains__(self, name):
        return any(g.name == name for g in self._list)

    def __getitem__(self, name):
        g = self.get(name)
        if g is None:
            raise KeyError(name)
        return g

    def __iter__(self):
        return iter(self._list)

    def __len__(self):
        return len(self._list)


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------

class FakeMeshData:
    def __init__(self):
        self.vertices = []


class FakeModifier:
    def __init__(self, type_, object_):
        self.type = type_
        self.object = object_
        self.name = "Armature"


class FakeMeshObject:
    type = 'MESH'

    def __init__(self, name, armature_obj):
        self.name = name
        self.data = FakeMeshData()
        self.vertex_groups = FakeVertexGroups(self)
        self.matrix_world = IdentityMatrix()
        self.modifiers = [FakeModifier('ARMATURE', armature_obj)]

    def add_vertex(self, co):
        v = FakeVertex(len(self.data.vertices), co)
        self.data.vertices.append(v)
        return v

    def set_weight(self, vidx, group_name, weight):
        vg = self.vertex_groups.get(group_name) or self.vertex_groups.new(name=group_name)
        vg.add([vidx], weight, 'REPLACE')


class FakePoseBone:
    def __init__(self, data_bone):
        self._b = data_bone
        self.lock_location = (False,) * 3
        self.lock_rotation = (False,) * 3

    @property
    def name(self):
        return self._b.name

    @property
    def head(self):
        return self._b.head_local

    @property
    def tail(self):
        return self._b.tail_local


class FakePose:
    def __init__(self, arm_data):
        self.bones = _PoseBoneCollection(arm_data)


class _PoseBoneCollection:
    def __init__(self, arm_data):
        self._arm_data = arm_data
        self._cache = {}

    def get(self, name, default=None):
        b = self._arm_data.bones.get(name)
        if b is None:
            return default
        if name not in self._cache:
            self._cache[name] = FakePoseBone(b)
        return self._cache[name]

    def __iter__(self):
        return (self.get(b.name) for b in self._arm_data.bones)


class FakeArmatureObject:
    type = 'ARMATURE'

    def __init__(self, arm_data, name="Armature"):
        self.name = name
        self.data = arm_data
        self.matrix_world = IdentityMatrix()
        self.pose = FakePose(arm_data)


# ---------------------------------------------------------------------------
# the bpy module
# ---------------------------------------------------------------------------

class _Operator:
    def report(self, level, msg):
        print(f"    [op.report {'/'.join(sorted(level))}] {msg}")


def install(objects):
    """Create and install a fake bpy with `objects` as bpy.data.objects."""
    bpy = types.ModuleType("bpy")
    bpy.data = types.SimpleNamespace(objects=list(objects))
    bpy.types = types.SimpleNamespace(Operator=_Operator)
    bpy.props = types.SimpleNamespace(
        StringProperty=lambda **k: None,
        BoolProperty=lambda **k: None,
        EnumProperty=lambda **k: None,
    )
    active = next((o for o in objects if o.type == 'ARMATURE'), None)
    bpy.context = types.SimpleNamespace(
        active_object=active,
        mode='OBJECT',
        view_layer=types.SimpleNamespace(
            objects=types.SimpleNamespace(active=active),
            update=lambda: None,
        ),
    )
    bpy.ops = types.SimpleNamespace(
        object=types.SimpleNamespace(mode_set=lambda **k: {'FINISHED'}),
    )
    sys.modules["bpy"] = bpy
    return bpy


class FakeContext:
    def __init__(self, active_object):
        self.active_object = active_object
        self.mode = 'OBJECT'
