"""
API Routes Package

This package contains FastAPI route handlers for the application.
Each module defines routes for a specific feature area:

- auth.py: Authentication routes (login, logout, magic link verification)
- feed.py: Feed routes (post messages, star, threading, streaming)

Routes are registered in main.py using FastAPI's router system,
which allows for modular organization and shared route prefixes.
"""
