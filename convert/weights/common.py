"""Shared weight/geometry helpers for the conversion engine.

Centralises the small operations that the old code repeated inline in ~8
places (find the meshes skinned to an armature, read a vertex's weight in a
group, project a vertex onto a bone axis). Having one definition each keeps
the weight modules short and makes the *reuse vs. split* split (req 1) easy to
read: every weight module imports these and only adds its own policy.
"""

import bpy


def find_main_armature():
    """Return the active non-backup armature in the scene, or None.

    Several operators can be invoked with a mesh (or nothing) active; they all
    need the real armature. One definition instead of the copy in every file.
    """
    obj = bpy.context.active_object
    if obj and obj.type == 'ARMATURE' and 'backup' not in obj.name.lower():
        return obj
    return next((o for o in bpy.data.objects
                 if o.type == 'ARMATURE' and 'backup' not in o.name.lower()), None)


def skinned_meshes(arm):
    """Meshes that have an ARMATURE modifier bound to `arm`.

    This is the canonical "which meshes carry this rig's weights" query used
    everywhere. (Matches the old `any(mod.type=='ARMATURE' and mod.object==arm)`
    idiom; a couple of old call-sites also accepted `mesh.parent == arm`, but
    every converted mesh has the modifier, so the modifier test is sufficient
    and unambiguous.)
    """
    out = []
    for m in bpy.data.objects:
        if m.type != 'MESH':
            continue
        if any(md.type == 'ARMATURE' and md.object == arm for md in m.modifiers):
            out.append(m)
    return out


def vgroup_weight(vertex, group_index):
    """Weight of `vertex` in the vertex group with index `group_index` (0 if none)."""
    for g in vertex.groups:
        if g.group == group_index:
            return g.weight
    return 0.0


def bone_axis_world(arm, head_name, tail_name):
    """Return (origin_world, axis_world, length_sq) for the segment head→tail.

    `head_name`/`tail_name` are bone names; the axis runs from the first bone's
    head to the second bone's head (the convention every arm/leg split uses).
    Returns None if either bone is missing or the segment is degenerate.
    """
    a = arm.data.bones.get(head_name)
    b = arm.data.bones.get(tail_name)
    if not a or not b:
        return None
    mw = arm.matrix_world
    o = mw @ a.head_local
    axis = (mw @ b.head_local) - o
    l2 = axis.length_squared
    if l2 < 1e-9:
        return None
    return o, axis, l2


def axis_param(point_world, origin, axis, length_sq):
    """Projection parameter t of a world point onto a bone axis (0=head, 1=tail)."""
    return (point_world - origin).dot(axis) / length_sq


def ensure_vgroup(mesh, name):
    """Get or create a vertex group by name."""
    return mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
