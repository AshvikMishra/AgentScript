"""AgentScript: a tiny language and compiler for safe AI agent programs."""

import sys

__version__ = "0.1.0"

# INT literals are unbounded (brief section 1, `[0-9]+`) and run values can grow without bound,
# so lift Python's 4300-digit int<->str conversion limit for the lexer, optimizer and JSON.
sys.set_int_max_str_digits(0)
