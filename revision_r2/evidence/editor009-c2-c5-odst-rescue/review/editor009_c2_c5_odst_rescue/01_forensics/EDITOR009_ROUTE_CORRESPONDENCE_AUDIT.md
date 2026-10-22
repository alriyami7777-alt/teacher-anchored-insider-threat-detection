# EDITOR-009 Route Correspondence Audit

ROUTE_INDEX_IDENTITY_ASSUMED = YES

`live_odst_forward` concatenates per-layer `choice` tensors along the tree axis:
`(B, n_trees, depth)` per Dense layer → `(B, n_layers * n_trees, depth)`.

`route_consistency_loss` then compares `student_p` and `teacher_p` elementwise at the same index.

## Teacher initialisation

Student trees inherit teacher trees at init (parity check requires exact route match).
Index j ↔ j is structurally meaningful at epoch 0 and remains a correspondence of *descendants of the same initial tree*, even after training.

## Random initialisation

Student trees are independently initialised. Teacher tree j and student tree j have no shared identity.
RAW_INDEX_CORRESPONDENCE_IS_STRUCTURALLY_INVALID_UNDER_RANDOM_INIT = SUPPORTED

This is a primary candidate mechanism for C6 collapse: the route KL forces unmatched random trees toward an arbitrary teacher index.
