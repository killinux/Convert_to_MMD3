"""Fake Blender data structures for offline (no-bpy) testing.

FakeBone/FakeArmatureData mimic exactly the bpy.types.Bone / bpy.types.Armature
surface that skeleton_identifier.py and helper_classifier.py touch:
bones iteration, bones.get(), bone.name/.head_local/.tail_local/.parent/
.children/.use_deform. Geometry is armature-data space, Z-up, +X = character
left (the same contract real imports satisfy).
"""

from mathutils import Vector


class FakeBone:
    def __init__(self, name, head, tail=None, parent=None, use_deform=True):
        self.name = name
        self.head_local = Vector(head)
        self.tail_local = Vector(tail) if tail is not None else self.head_local + Vector((0, 0, 0.05))
        self.parent = parent
        self.children = []
        self.use_deform = use_deform
        self.use_connect = False
        self.roll = 0.0
        self.hide = False
        if parent is not None:
            parent.children.append(self)

    # edit-bone aliases (edit bones expose .head/.tail; data bones .head_local)
    @property
    def head(self):
        return self.head_local

    @head.setter
    def head(self, v):
        self.head_local = Vector(tuple(v))

    @property
    def tail(self):
        return self.tail_local

    @tail.setter
    def tail(self, v):
        self.tail_local = Vector(tuple(v))

    def __repr__(self):
        return f"FakeBone({self.name!r})"


class _BoneCollection:
    def __init__(self):
        self._list = []
        self._by_name = {}

    def add(self, bone):
        self._list.append(bone)
        self._by_name[bone.name] = bone

    def get(self, name, default=None):
        return self._by_name.get(name, default)

    def new(self, name):
        """Edit-bone style creation (head/tail set by the caller afterwards)."""
        b = FakeBone(name, (0, 0, 0), (0, 0, 0.01))
        self.add(b)
        return b

    def __getitem__(self, name):
        return self._by_name[name]

    def __contains__(self, name):
        return name in self._by_name

    def __iter__(self):
        return iter(self._list)

    def __len__(self):
        return len(self._list)


class FakeArmatureData:
    """Stands in for bpy.types.Armature (the `armature.data` object)."""

    def __init__(self, name="Armature"):
        self.name = name
        self.bones = _BoneCollection()

    @property
    def edit_bones(self):
        return self.bones

    def bone(self, name, head, tail=None, parent=None, use_deform=True):
        """Create a bone; `parent` may be a FakeBone or a bone name."""
        if isinstance(parent, str):
            parent = self.bones[parent]
        b = FakeBone(name, head, tail, parent, use_deform)
        self.bones.add(b)
        return b
