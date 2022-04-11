"""Contains stream expressions and statements"""

from abc import ABC
import functools
from multiprocessing.sharedctypes import Value
import operator
from typing import List, Optional, Sequence, Tuple, Union
from typing_extensions import Self


from .enums import FillDateTypeString, JoinType, Order
from .field import field
from .scalar import BinaryOperation, Scalar
from .expression import Expression
from .util import stringify


class StreamStatement(ABC):
    """Base class for a stream SAQL statement

    Each SAQL statement has an input stream, an operation, and an output stream.
    """

    stream: "Stream"


class Stream(Expression):
    """Base class for a SAQL data stream"""

    _id: int
    _statements: List[StreamStatement]

    def __init__(self) -> None:
        """Initializer"""
        super().__init__()
        self._id = 0
        self._statements: List[StreamStatement] = []

    def __str__(self) -> str:
        """Cast the stream to a string"""
        return "\n".join(str(op) for op in self._statements)

    @property
    def ref(self) -> str:
        """Stream reference in the SAQL query"""
        return f"q{self._id}"

    def foreach(self, *fields: Scalar) -> Self:
        """Applies a set of expressions to every row in a dataset.

        This action is often referred to as projection

        Args:
            fields: One or more fields to project

        Returns:
            self

        """
        self._statements.append(ProjectionStatement(self, fields))
        return self

    def group(self, *fields: Scalar) -> Self:
        """Organizes the rows returned from a query into groups

        Within each group, you can apply an aggregate function, such as count() or sum()
        to get the number of items or sum, respectively.

        Args:
            fields: One or more fields to group by

        Returns:
            self

        """
        self._statements.append(GroupStatement(self, fields))
        return self

    def filter(self, *filters: BinaryOperation) -> Self:
        """Selects rows from a dataset based on a filter predicate

        Args:
            filters: One or more filters. If multiple filter arguments are provided,
                they will be combined using `and`.

        Returns:
            self

        """
        self._statements.append(FilterStatement(self, filters))
        return self

    def order(self, *fields: Union[Scalar, Tuple[Scalar, Order]]) -> Self:
        """Sorts in ascending or descending order on one or more fields.

        Args:
            fields: One or more fields to sort by

        Returns:
            self

        """
        self._statements.append(OrderStatement(self, fields))
        return self

    def limit(self, limit: int) -> Self:
        """Limits the number of rows returned.

        Args:
            limit: Maximum number of rows to return. Max 10,000

        Returns:
            self

        """
        self._statements.append(LimitStatement(self, limit))
        return self

    def fill(
        self,
        date_cols: Sequence[field],
        date_type_string: FillDateTypeString,
        partition: Optional[field] = None,
    ) -> Self:
        """Fills missing date values by adding rows in data stream

        Args:
            date_cols: Date fields to check
            date_type_string: Date column type string for formatting dates that get
                injected into the stream
            partition: Optional dimension field used to partition the data stream.
                Defaults to None.

        Returns:
            self

        """
        self._statements.append(
            FillStatement(self, date_cols, date_type_string, partition=partition)
        )
        return self


class LoadStatement(StreamStatement):
    """Statement to load a dataset"""

    def __init__(self, stream: Stream, name: str) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            name: Name of the dataset to load

        """
        super().__init__()
        self.stream = stream
        self.name = name

    def __str__(self) -> str:
        """Cast this load statement to a string"""
        return f'{self.stream.ref} = load "{self.name}";'


class ProjectionStatement(StreamStatement):
    """Statement to project columns from a stream"""

    def __init__(self, stream: Stream, fields: List[Scalar]) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            fields: One or more fields to project

        """
        super().__init__()
        self.stream = stream
        self.fields = fields

    def __str__(self) -> str:
        """Cast this projection statement to a string"""
        fields = ", ".join(str(f) for f in self.fields)
        return f"{self.stream.ref} = foreach {self.stream.ref} generate {fields};"


class OrderStatement(StreamStatement):
    """Statement to order rows in a stream"""

    def __init__(
        self,
        stream: Stream,
        fields: Union[Scalar, List[Scalar], List[Tuple[Scalar, Order]]],
    ) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            fields: One or more fields to order by

        """
        super().__init__()
        self.stream = stream
        self.fields = fields

    def __str__(self) -> str:
        """Cast this order statement to a string"""
        fields = []
        for f in self.fields:
            if isinstance(f, Scalar):
                fields.append(f"{f} asc")
            else:
                fields.append(f"{f[0]} {f[1]}")

        if len(fields) > 1:
            fields = f"({', '.join(fields)})"
        else:
            fields = fields[0]

        return f"{self.stream.ref} = order {self.stream.ref} by {fields};"


class LimitStatement(StreamStatement):
    """Statement to limit the number of rows returned from a stream"""

    def __init__(self, stream: Stream, limit: int):
        """Initializer

        Args:
            stream: Stream containing this statement
            limit: Maximum number of rows to return. Max 10,000

        """
        super().__init__()
        self.stream = stream
        if limit > 10_000:
            raise ValueError(f"Limit must not exceed 10,000. Provided: {limit}")
        self.limit = limit

    def __str__(self) -> str:
        """Cast this limit statement to a string"""
        return f"{self.stream.ref} = limit {self.stream.ref} {self.limit};"


class GroupStatement(StreamStatement):
    """Statement to group rows in a stream"""

    def __init__(self, stream: Stream, fields: List[Scalar]):
        """Initializer

        Args:
            stream: Stream containing this statement
            fields: One or more fields to group by

        """
        super().__init__()
        self.stream = stream
        self.fields = fields

    def __str__(self) -> str:
        """Cast this group statement to a string"""
        fields = ", ".join(str(f) for f in self.fields)
        return f"{self.stream.ref} = group {self.stream.ref} by {fields};"


class FilterStatement(StreamStatement):
    """Statement to filter rows in a stream"""

    def __init__(self, stream: Stream, filters: List[BinaryOperation]) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            filters: One or more operations to filter rows in a stream

        """
        super().__init__()
        self.stream = stream
        self.filters = filters

    def __str__(self) -> str:
        """Cast this filter statement to a string"""
        expr = functools.reduce(
            lambda left, right: BinaryOperation(operator.and_, left, right),
            self.filters,
        )
        return f"{self.stream.ref} = filter {self.stream.ref} by {expr};"


class CogroupStatement(StreamStatement):
    """Statement to combine (join) two or more streams into one"""

    def __init__(
        self,
        stream: Stream,
        streams: List[Tuple[Stream, Scalar]],
        join_type: JoinType = JoinType.inner,
    ) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            streams: List of tuples that each define the stream to combine and the
                common field that will be used to combine results
            join_type: Type of join that determines how records are included in the
                combined stream

        """
        super().__init__()
        self.stream = stream
        self.streams = streams
        self.join_type = join_type

    def __str__(self) -> str:
        """Cast this cogroup statement to a string"""
        lines = []
        streams = []
        for i, item in enumerate(self.streams):
            stream, field_ = item
            s = f"{stream.ref} by {field_}"
            if i == 0 and self.join_type != JoinType.inner:
                s += f" {self.join_type}"

            streams.append(s)
            lines.append(str(stream))

        lines.append(f"{self.stream.ref} = cogroup {', '.join(streams)};")

        return "\n".join(lines)


class FillStatement(StreamStatement):
    """Statement to fill a data stream with missing dates"""

    def __init__(
        self,
        stream: Stream,
        date_cols: Sequence[field],
        date_type_string: FillDateTypeString,
        partition: Optional[field] = None,
    ) -> None:
        """Initializer

        Args:
            stream: Stream containing this statement
            date_cols: Date fields to check
            date_type_string: Date column type string for formatting dates that get
                injected into the stream
            partition: Optional dimension field used to partition the data stream.
                Defaults to None.

        """
        super().__init__()
        self.stream = stream
        self.date_cols = date_cols
        self.date_type_string = date_type_string
        self.partition = partition

    def __str__(self) -> str:
        """Cast this fill statement to a string"""
        args = [
            f"dateCols=({','.join(str(c) for c in self.date_cols)}, {stringify(str(self.date_type_string))})"
        ]
        if self.partition:
            args.append(f"partition={stringify(self.partition)}")

        return f"{self.stream.ref} = fill {self.stream.ref} by ({', '.join(args)});"


class load(Stream):
    """Load a dataset"""

    def __init__(self, name: str):
        """Initializer

        Args:
            name: Name of the dataset to load

        """
        super().__init__()
        self._statements.append(LoadStatement(self, name))


class cogroup(Stream):
    """Combine data from two or more data streams into a single data stream"""

    join_type: JoinType

    def __init__(
        self, *streams: Tuple[Stream, Scalar], join_type: JoinType = JoinType.inner
    ) -> None:
        """Initializer

        Args:
            streams: Each item is a tuple of the stream to combine and the common field
                that will be used to combine results
            join_type: Type of join that determines how records are included in the
                combined stream. Defaults to JoinType.inner.

        """
        super().__init__()
        # A cogroup implies that there are multiple streams. Therefore, we need to
        # increment the stream IDs so each stream in the query has a unique reference.
        max_id = 0
        for i, (stream, _) in enumerate(streams):
            stream._id += i
            max_id = max(max_id, stream._id)
        self._id = max_id + 1
        self._statements.append(CogroupStatement(self, streams, join_type))
