SOURCE_DATE_EPOCH := 1787745600

.PHONY: all figures manuscript

all: manuscript

figures:
	python3 make_figures.py

manuscript: figures
	SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) tectonic cs_upper_bound.tex
