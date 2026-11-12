"""相似账号人工配置与公开主页解析。"""

from .benchmark_generation import (
    BenchmarkSimilarResult,
    generate_benchmark_similar_accounts,
)
from .metadata import (
    MAX_MANUAL_SIMILAR_ACCOUNTS,
    effective_similar_accounts,
    normalize_public_profile_url,
    same_similar_account,
    similar_account_key,
    with_configuration_metadata,
)
from .resolver import SimilarAccountResolver

__all__ = [
    "BenchmarkSimilarResult",
    "SimilarAccountResolver",
    "MAX_MANUAL_SIMILAR_ACCOUNTS",
    "effective_similar_accounts",
    "generate_benchmark_similar_accounts",
    "normalize_public_profile_url",
    "same_similar_account",
    "similar_account_key",
    "with_configuration_metadata",
]
