# arXiv submission bundle

This directory contains the arXiv-oriented LaTeX source for the PermeantOS/USXF paper.

Files:

- `permeantos-usxf.tex`: main LaTeX source.
- `references.bib`: bibliography.

Recommended local build:

```bash
pdflatex permeantos-usxf.tex
bibtex permeantos-usxf
pdflatex permeantos-usxf.tex
pdflatex permeantos-usxf.tex
```

For arXiv submission, upload:

- `permeantos-usxf.tex`
- `references.bib`

If you build locally and prefer uploading generated bibliography state, upload the generated `.bbl` as well.

Suggested primary arXiv category:

- `cs.DC` Distributed, Parallel, and Cluster Computing

Possible cross-list categories:

- `cs.AI`
- `cs.LG`
- `cs.SE`

Before submission:

- Confirm author names and affiliations.
- Confirm whether any additional contributors should be listed or acknowledged.
- Replace placeholder/preprint references with canonical citations where available.
- Build and inspect the generated PDF.
- Ensure the claims match the current public repository and release tag/commit.
