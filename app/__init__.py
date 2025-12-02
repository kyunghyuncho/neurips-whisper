"""
NeurIPS Whisper Application Package

This package contains the main application code for the NeurIPS Whisper
town square messaging application. The package is organized as follows:

- config.py: Application configuration and environment settings
- database.py: Database connection and session management
- dependencies.py: FastAPI dependency injection functions
- limiter.py: Rate limiting configuration
- main.py: FastAPI application entry point and route definitions
- models.py: SQLAlchemy ORM database models
- templating.py: Jinja2 template configuration

Subpackages:
- routes/: API route handlers (auth, feed)
- services/: Business logic services (auth, email, feed, audit)
- utils/: Utility functions (text processing, validators)
- templates/: HTML templates for server-side rendering
- static/: Static assets (CSS, images)
"""
