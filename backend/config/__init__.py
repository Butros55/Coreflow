"""Coreflow Django project configuration."""

from config.celery import app as celery_app

__all__ = ("celery_app",)
