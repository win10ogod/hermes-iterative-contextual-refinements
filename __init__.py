"""Directory-plugin shim for Hermes Agent.

Hermes directory plugins import this file as a generated namespace package.
The implementation lives in the normal Python package so pip entry points and
directory loading share the same register function.
"""

try:
    from .hermes_iterative_contextual_refinements import register
except ImportError:  # pytest may import this file as a top-level test package.
    from hermes_iterative_contextual_refinements import register

__all__ = ["register"]
