"""评审应用的领域异常。

单独一个模块，好让下层（抽签、查询）也能抛同一种错误，而不必反过来 import
服务层——那会绕成一个环。
"""


class ReviewError(Exception):
    """A submission or review action violates a business rule."""
