# Building the manuscript

The checked-in figures are regenerated from `make_figures.py`, and the paper
is compiled with Tectonic 0.15.0. The complete build is:

```sh
uv sync --frozen --group paper
uv run --frozen --group paper make -C paper
```

The `paper` dependency group is locked in `uv.lock`; Tectonic must be exactly
0.15.0. The Makefile pins `SOURCE_DATE_EPOCH`, and the figure script removes
creation/modification timestamps from its PDF metadata. Repeating the build
with the documented versions produces the same PDF hashes. It does not run the
upper-bound engine, rebuild the `h=10` graph, or perform a new `z` search.
