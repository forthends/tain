"""
Tao Agent Runtime — standalone execution kernel for exported agents.

This package is the "engine" that powers an evolved agent after it leaves
the factory (tain_agent framework). It has zero internal dependencies on
tain_agent and only requires stdlib + pip packages (anthropic, openai, rich).

Design constraint: no ``import tain_agent`` anywhere in this package.
"""

__version__ = "3.0.0-dev"
