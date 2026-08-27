# Future full-h10 oracle validation contract

## Status

The full history-10 oracle validation has **not** been run. The repository does not contain
`h10-oracle-full.json`, and no result from that filename is part of the current evidence.
The command exists so a future adequately provisioned run can close the remaining semantic
coverage gap. It recomputes 15,209,626,046 transitions and must not be treated as a routine
unit or CI check.

## Command

After independently building the authenticated h=10 graph:

```sh
python3 verify_graph_oracle.py full \
  --graph-dir upper_graphs/h10 \
  --workers 16 \
  --chunk 200000 \
  --index oracle-index-h10 \
  --progress h10-oracle-full.progress \
  --output h10-oracle-full.json
```

No run was performed while adding this contract. The change also did not build the h=10 graph
or fetch the multi-gigabyte witness.

## Authenticated inputs

The command must refuse any graph that does not authenticate through `graph.json`. The
expected record inputs are:

| input | bytes | SHA-256 |
|---|---:|---|
| `states.u64` | 3,202,026,536 | `defc127da935708620977efddda218378322d9d23921ac3453c9f7a56ff5f59b` |
| `transitions.u32` | 60,838,504,184 | `611a32eb44baa93fbe5231aa8ddaf9aa690da4e4b2a049ff54226ce3e265aba5` |

Their canonical graph identity is
`e4db7c10b0b55060c3a9beff010583a593b4c24bc13600ecb219b933a2806f7a`.
The graph has 400,253,317 states, 38 columns, and reject sentinel `2^32-1`.

The `.ordered.npy` and `.ordering.npy` files under `--index` are derived lookup indexes, not
trusted inputs. Before the full comparison, the verifier checks their shape, index range,
strict ordering and uniqueness, and exact correspondence to the authenticated state table.

## Output schema

The JSON output is an object with:

- `mode`, `history`, `states`, `columns`, `rows_checked`, and `transitions_checked`;
- `workers` and descriptive `seconds`;
- `graph_identity_states_sha256` and `graph_identity_transitions_sha256`;
- `contract`, containing `start_state_correct`, `state_uniqueness`,
  `lookup_index_validated`, `quotient_canonical`, `successor_closure`, `reachable_states`,
  `all_states_reachable`, `rows_checked`, `transitions_checked`,
  `spurious_rejections`, `missing_successors`, `transition_mismatches`, and
  `reference_complete`;
- top-level `status`.

Timing and worker count are descriptive. Counts, hashes, invariants, and mismatch totals are
the acceptance fields.

## Acceptance gate

A future result is accepted only if all of the following hold:

1. The two input hashes equal the values above.
2. `mode == "full"`, `history == 10`, `states == rows_checked == 400253317`,
   `columns == 38`, and `transitions_checked == 15209626046`.
3. The correct initial state is row zero; the lookup index is validated against the state
   table; and all encoded states are unique canonical simultaneous-complement representatives.
4. Every nonrejecting successor is in range and all states are reachable from the start.
5. Every row and column agrees with the independent Figure 7 reference transition,
   including rejection and quotient reduction.
6. All three mismatch counts are zero, `reference_complete` is true, and top-level
   `status == "PASS"`.
7. The completed JSON file's SHA-256 is published alongside the result; future repository
   text must cite both that hash and the exact commit used for the run.

Until every gate is met, the remaining claim is exactly the current one: exhaustive semantic
agreement through h=6, a 760,000-transition h=10 spot-check, and no exhaustive h=10 oracle
result.
