"""
Jinja2 Template Configuration

Centralized template loader for rendering HTML responses.
This instance is imported by route handlers to render templates.
"""

from fastapi.templating import Jinja2Templates


# Global templates instance pointing to the templates directory
# Used to render HTML templates with context data from routes
templates = Jinja2Templates(directory="app/templates")
