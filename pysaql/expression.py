"""Contains base Expression class"""


from abc import ABC, abstractmethod
from typing import Optional

from .util import escape_identifier


class Expression(ABC):
    """Base expression class

    This is used as the root class for all expressions to establish inheritance and
    provide common methods.
    """

    _alias: Optional[str] = None

    def alias(self, name: str) -> "Expression":
        """Set the alias name

        Args:
            name: Alias name

        Returns:
            new expression object with alias

        """
        self._alias = name
        return self

    @abstractmethod
    def to_string(self) -> str:
        """Cast the expression to a string"""
        pass

    def __str__(self) -> str:
        """Cast the expression to a string, including the alias if set

        Returns:
            string

        """
        s = self.to_string()
        if self._alias:
            s += f" as {escape_identifier(self._alias)}"

        return s
