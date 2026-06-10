"""SPLIT exception: distribute a parent bone's weight onto an inserted child.

When `complete` inserts an intermediate bone that XPS never had — 上半身1 (between
上半身 and 上半身2) or 首1 (between 首 and 頭) — that bone starts empty. This splits
the parent's weight along the segment so the new bone deforms. Also used for
armpit smoothing (肩→腕, additive, `src_keep_floor=1.0` so 肩 weight is not thinned).

This is genuinely a *split* (the inserted bone has no XPS source), so it lives in
its own module rather than the reuse path.
"""

from .common import skinned_meshes


def split_chain_weights(obj, src_name, dst_name, seg_from_name, seg_to_name,
                        perp_threshold=1.5, src_keep_floor=0.0):
    """PMXEditor-style: along seg_from→seg_to, move `src` weight to `dst` by t∈[0,1].

    Returns (moved_verts, filtered_verts). `src_keep_floor=1.0` only adds to dst
    without thinning src (armpit smoothing).
    """
    src_keep_floor = max(0.0, min(1.0, src_keep_floor))
    src_b = obj.data.bones.get(seg_from_name)
    dst_b = obj.data.bones.get(seg_to_name)
    if not src_b or not dst_b:
        return (0, 0)
    seg_from = src_b.head_local
    seg_to = dst_b.head_local
    if (seg_to - seg_from).length_squared < 1e-9:
        return (0, 0)
    meshes = skinned_meshes(obj)
    arm_mw = obj.matrix_world
    seg_from_w = arm_mw @ seg_from
    seg_to_w = arm_mw @ seg_to
    seg_w = seg_to_w - seg_from_w
    seg_len_sq_w = seg_w.length_squared
    if seg_len_sq_w < 1e-9:
        return (0, 0)
    perp_limit_sq = (perp_threshold * perp_threshold) * seg_len_sq_w
    moved = 0
    filtered = 0
    for m in meshes:
        src_vg = m.vertex_groups.get(src_name)
        if not src_vg:
            continue
        if dst_name not in m.vertex_groups:
            m.vertex_groups.new(name=dst_name)
        dst_vg = m.vertex_groups[dst_name]
        mesh_mw = m.matrix_world
        plans = []
        for v in m.data.vertices:
            src_w = 0.0
            existing_dst = 0.0
            for g in v.groups:
                if g.group == src_vg.index:
                    src_w = g.weight
                elif g.group == dst_vg.index:
                    existing_dst = g.weight
            if src_w <= 0:
                continue
            rel = (mesh_mw @ v.co) - seg_from_w
            t = rel.dot(seg_w) / seg_len_sq_w
            t = max(0.0, min(1.0, t))
            if t <= 0:
                continue
            perp_sq = rel.length_squared - t * t * seg_len_sq_w
            if perp_sq > perp_limit_sq:
                filtered += 1
                continue
            new_src = src_w * (1.0 - t * (1.0 - src_keep_floor))
            new_dst = existing_dst + src_w * t
            plans.append((v.index, new_src, new_dst))
        for v_idx, new_src, new_dst in plans:
            if new_src > 1e-6:
                src_vg.add([v_idx], new_src, 'REPLACE')
            else:
                src_vg.remove([v_idx])
            if new_dst > 1e-6:
                dst_vg.add([v_idx], new_dst, 'REPLACE')
            moved += 1
    return (moved, filtered)
