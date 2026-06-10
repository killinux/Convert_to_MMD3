"""Weight finalize: cull dust, limit to 4 bones per vertex, normalize.

PMX deforms with at most 4 bones per vertex and expects normalized weights.
mmd_tools' exporter handles violations by sorting, keeping the top 4 and
renormalizing — with NO small-weight threshold (confirmed in
mmd_tools/core/pmx/exporter.py), so a vertex that accumulated 5+ groups
through fold + τ split + palm keeps two near-zero dust entries and silently
drops a real contributor. XPS input is also allowed to be non-normalized
(the format does not require it and XNALaraMesh imports weights verbatim).

So the converter owns the truncation decision itself, once, at the end of the
weight chain: per vertex — drop dust below CULL_THRESHOLD, keep the 4 largest,
renormalize to 1.0. Only deform-bone groups are touched; helper groups that
were deliberately preserved (physics strands, face bones) participate like
any other deform group, and non-bone vertex groups (mmd_vertex_order, sdef
masks, pin groups) are left alone.
"""

import bpy

from .common import skinned_meshes, find_main_armature

CULL_THRESHOLD = 0.005   # absolute dust cutoff (PMXEditor practice: 0.5~1%)
MAX_BONES = 4


def sanitize_mesh_weights(arm, mesh):
    """Cull/limit/normalize all deform-bone weights of one mesh. Returns
    (vertices_touched, groups_culled)."""
    bones = arm.data.bones
    deform_idx = set()
    for vg in mesh.vertex_groups:
        b = bones.get(vg.name)
        if b is not None and getattr(b, "use_deform", True):
            deform_idx.add(vg.index)
    if not deform_idx:
        return (0, 0)

    idx_to_vg = {vg.index: vg for vg in mesh.vertex_groups}
    touched = 0
    culled = 0
    for v in mesh.data.vertices:
        entries = [(g.group, g.weight) for g in v.groups
                   if g.group in deform_idx and g.weight > 0.0]
        if not entries:
            continue
        total = sum(w for _, w in entries)
        kept = [(i, w) for i, w in entries if w >= CULL_THRESHOLD]
        if not kept:  # all dust: keep the single largest so the vertex stays bound
            kept = [max(entries, key=lambda e: e[1])]
        kept.sort(key=lambda e: -e[1])
        dropped = [(i, w) for i, w in entries if (i, w) not in kept[:MAX_BONES]]
        kept = kept[:MAX_BONES]

        ksum = sum(w for _, w in kept)
        needs_norm = abs(ksum - 1.0) > 1e-4
        if not dropped and not needs_norm:
            continue

        for i, _ in dropped:
            idx_to_vg[i].remove([v.index])
            culled += 1
        if ksum > 1e-9:
            for i, w in kept:
                idx_to_vg[i].add([v.index], w / ksum, 'REPLACE')
        touched += 1
    return (touched, culled)


def sanitize_weights(arm):
    """Run the finalize pass over every mesh skinned to `arm`."""
    total_v = 0
    total_c = 0
    for mesh in skinned_meshes(arm):
        tv, tc = sanitize_mesh_weights(arm, mesh)
        total_v += tv
        total_c += tc
    return total_v, total_c


class OBJECT_OT_sanitize_weights(bpy.types.Operator):
    """权重收尾：剔除微小残渣、限制每顶点≤4骨、归一化（PMX 导出前必跑）"""
    bl_idname = "object.sanitize_weights"
    bl_label = "权重收尾(剔渣+4骨+归一)"
    bl_description = "逐顶点剔除<0.5%残渣权重、保留最大4骨并归一化——把截断决策握在转换器手里而不是 mmd_tools 导出兜底"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            obj = find_main_armature()
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未找到骨架")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        nv, nc = sanitize_weights(obj)
        self.report({'INFO'}, f"权重收尾: 调整 {nv} 顶点, 剔除 {nc} 条残渣权重")
        return {'FINISHED'}
