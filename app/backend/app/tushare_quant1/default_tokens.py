"""Default Tushare token fallback.

Real tokens must be configured through QUANT1_TUSHARE_TOKENS, TUSHARE_TOKEN,
or config/secrets/tushare_tokens.json. Keep credentials out of git.
"""

TUSHARE_DEFAULT_TOKENS: tuple[str, ...] = ()
