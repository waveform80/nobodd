#!/usr/bin/env python3
# vim: set fileencoding=utf-8:
#
# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import sys
import os
import tomllib
import datetime as dt
from pathlib import Path

on_rtd = os.environ.get('READTHEDOCS', '').lower() == 'true'
with (Path(__file__).parent / '..' / 'pyproject.toml').open('rb') as f:
    info = tomllib.load(f)['project']

# -- Project information -----------------------------------------------------

project = info['name']
author = info['authors'][0]['name']
now = dt.datetime.now(tz=dt.timezone.utc)
copyright = (
    f'2023-{now:%Y} {author}' if now.year > 2023 else f'2023 {author}')
release = info['version']
version = release

# -- General configuration ------------------------------------------------

needs_sphinx = '4.0'
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.imgmath',
]
if on_rtd:
    tags.add('rtd')

root_doc = 'index'
templates_path = ['_templates']
exclude_patterns = ['_build']
highlight_language = 'python3'
pygments_style = 'sphinx'

# -- Autodoc configuration ------------------------------------------------

autodoc_member_order = 'groupwise'
autodoc_default_options = {
    'members': True,
}
autodoc_mock_imports = []

# -- Intersphinx configuration --------------------------------------------

intersphinx_mapping = {
    'python': ('https://docs.python.org/3.12', None),
}

# -- Options for HTML output ----------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_title = f'{project} {version} Documentation'
html_static_path = ['_static']
manpages_url = 'https://manpages.ubuntu.com/manpages/noble/en/man{section}/{page}.{section}.html'

# -- Options for LaTeX output ---------------------------------------------

latex_engine = 'xelatex'

latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '10pt',
    'preamble': r'\def\thempfootnote{\arabic{mpfootnote}}', # workaround sphinx issue #2530
}

latex_documents = [
    (
        'index',            # source start file
        project + '.tex',   # target filename
        html_title,         # title
        author,             # author
        'manual',           # documentclass
        True,               # documents ref'd from toctree only
    ),
]

latex_show_pagerefs = True
latex_show_urls = 'footnote'

# -- Options for epub output ----------------------------------------------

epub_basename = project
epub_author = author
epub_identifier = f'https://{info["name"]}.readthedocs.io/'
epub_show_urls = 'no'

# -- Options for manual page output ---------------------------------------

man_pages = [
    (
        'cli-server',
        'nobodd-tftpd',
        'nobodd-tftpd - serve boot partition files over TFTP',
        [author['name'] for author in info['authors']],
        1,
    ),
    (
        'cli-prep',
        'nobodd-prep',
        'nobodd-prep - prepare an OS image for NBD netboot',
        [author['name'] for author in info['authors']],
        1,
    ),
    (
        'cli-sh',
        'nobodd-sh',
        'nobodd-sh - run shell-like commands against files within images',
        [author['name'] for author in info['authors']],
        1,
    ),
]

man_show_urls = True

# -- Options for linkcheck builder ----------------------------------------

linkcheck_retries = 3
linkcheck_workers = 20
linkcheck_anchors = True
