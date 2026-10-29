# Planning artifacts

The runtime planner ships the audited 25 km NEP static grid at
`backend/app/navigation/resources/grids/northeast_passage_25km_static.npz`.
Risk-grid outputs are written to `PLANNER_RESULT_ROOT` (default
`storage/navigation/plans`, Docker `/data/storage/navigation/plans`), not here.
