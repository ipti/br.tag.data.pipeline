# Sphinx Configuration - Sistema TIA
project = 'Sistema TIA - Data Warehouse'
copyright = '2024, Equipe de Dados'
author = 'Equipe de Dados'
release = '1.0.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.githubpages',
    'myst_parser',
    'sphinx_copybutton',
]

source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']

html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'style_nav_header_background': '#667eea',
}

myst_enable_extensions = ["colon_fence", "deflist", "tasklist"]
