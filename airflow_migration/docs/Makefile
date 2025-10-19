SPHINXBUILD = sphinx-build
SOURCEDIR = source
BUILDDIR = build

html:
	$(SPHINXBUILD) -b html $(SOURCEDIR) $(BUILDDIR)/html
	@echo ""
	@echo "✅ HTML estático gerado em: $(BUILDDIR)/html/"
	@echo "📂 Abra: $(BUILDDIR)/html/index.html"

clean:
	rm -rf $(BUILDDIR)/*
	@echo "🧹 Arquivos limpos"

.PHONY: html clean
