# vim: set noet sw=4 ts=4 fileencoding=utf-8:

PROJECT          = nobodd

PYTHON           = python3
PYFLAGS          =
PIP              = pip3
PYLINT           = pylint
RUFF             = ruff
PYTEST           = pytest
MSGINIT          = msginit
MSGMERGE         = msgmerge
MSGFMT           = msgfmt
XGETTEXT         = xgettext
SPHINX_BUILD     = sphinx-build
SPHINX_AUTOBUILD = sphinx-autobuild
SPHINXOPTS       =
SRCDIR           = $(PROJECT)
DOCSDIR          = docs
TESTSDIR         = tests
PODIR            = po
BUILDDIR         ?= build
SPHINX_HOST      ?= 127.0.0.1
SPHINX_PORT      ?= 8000

ALLSPHINXOPTS = -W -d $(BUILDDIR)/doctrees $(SPHINXOPTS) $(DOCSDIR)

POT_FILE    := $(PODIR)/$(PROJECT).pot
PO_FILES    := $(wildcard $(PODIR)/*.po)
MO_FILES    := $(patsubst $(PODIR)/%.po,po/mo/%/LC_MESSAGES/$(PROJECT).mo,$(PO_FILES))
PY_SOURCES  := $(wildcard $(SRCDIR)/*.py)
DOC_SOURCES := $(DOCSDIR)/conf.py \
               $(wildcard $(DOCSDIR)/*.rst) \
               $(wildcard $(DOCSDIR)/images/*.png) \
               $(wildcard $(DOCSDIR)/images/*.svg) \
               $(wildcard $(DOCSDIR)/images/*.dot) \
               $(wildcard $(DOCSDIR)/images/*.mscgen) \
               $(wildcard $(DOCSDIR)/images/*.gpi) \
               $(wildcard $(DOCSDIR)/images/*.pdf)

# Default target
all:
	@echo "make clean - Get rid of all generated files"
	@echo "make develop - Install editable version for development"
	@echo "make pot - Update translation template and sources"
	@echo "make mo - Generate translation files"
	@echo "make doc - Generate HTML and PDF documentation"
	@echo "make preview - Generate live preview of HTML documentation"
	@echo "make linkcheck - Check external links in HTML documentation"
	@echo "make lint - Run pylint against source"
	@echo "make test - Run tests"
	@echo "make sdist - Create source package"
	@echo "make wheel - Generate a PyPI wheel package"

clean:
	rm -rf $(BUILDDIR)

develop:
	$(PIP) install -e .[dev,doc,test]

sdist:
	$(PYTHON) -m build --sdist -o $(BUILDDIR)/dist .

wheel:
	$(PYTHON) -m build --wheel -o $(BUILDDIR)/dist .

doc:
	$(SPHINX_BUILD) -b html $(ALLSPHINXOPTS) $(BUILDDIR)/html
	$(SPHINX_BUILD) -b epub $(ALLSPHINXOPTS) $(BUILDDIR)/epub
	$(SPHINX_BUILD) -b latex $(ALLSPHINXOPTS) $(BUILDDIR)/latex
	$(MAKE) -C $(BUILDDIR)/latex all-pdf
	$(SPHINX_BUILD) -b man $(ALLSPHINXOPTS) $(BUILDDIR)/man

test:
	$(PYTEST) -v $(TESTSDIR)

lint:
	$(RUFF) check $(SRCDIR)
	$(PYLINT) $(SRCDIR)

linkcheck:
	$(SPHINX_BUILD) -b linkcheck $(ALLSPHINXOPTS) $(BUILDDIR)/linkcheck

preview:
	$(SPHINX_AUTOBUILD) --host $(SPHINX_HOST) --port $(SPHINX_PORT) $(DOCSDIR) $(BUILDDIR)/html

pot: $(POT_FILE) $(PO_FILES)

mo: $(MO_FILES)

$(POT_FILE): $(PY_SOURCES)
	$(XGETTEXT) -o $@ $(filter %.py,$^) $(filter %.ui,$^)

po/%.po: $(POT_FILE)
	$(MSGMERGE) -U $@ $<

po/mo/%/LC_MESSAGES/$(PROJECT).mo: po/%.po
	mkdir -p $(dir $@)
	$(MSGFMT) $< -o $@
