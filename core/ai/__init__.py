"""LLM-backed match verification and opportunity analysis.

Isolation rule: nothing in this package may import order execution, the risk
manager, the portfolio or any client order method. It receives plain data and
returns plain data. ``tests/test_ai_analyst.py`` enforces this with an AST scan.
"""
