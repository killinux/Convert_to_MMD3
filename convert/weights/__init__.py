"""Weight engine — reuse-first, with the split/synthesis exceptions separated out.

Modules:
  common    shared mesh/vgroup/axis helpers
  fold      fold planning (pure geometry, no bpy): which segment pool does a
            helper bone's weight join — name-agnostic twist-topology coverage
  transfer  REUSE path (default): deltoid ramp / segment fold / nearest valid
            deform bone, per helper (still pure reuse, never synthesises)
  chain     SPLIT: inserted 上半身1 / 首1 + armpit smoothing
  twist     SPLIT: arm weight → twist bones by τ-curve (conserving)
  palm      SYNTH: palm → metacarpals + thumb de-bleed (XPS has no metacarpals)
  sanitize  FINALIZE: cull dust, ≤4 bones per vertex, normalize (PMX contract)
"""
