# This file is part of daf_butler.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from __future__ import annotations

__all__ = ["QuerySummary"]  # other classes here are local to subpackage

import dataclasses
from collections.abc import Iterable, Iterator, Mapping, Set
from typing import Any, cast

import astropy.time
from lsst.daf.relation import ColumnExpression, ColumnTag, Predicate, SortTerm
from lsst.sphgeom import Region
from lsst.utils.classes import cached_getter, immutable
from sqlalchemy.sql import ColumnElement

from ...core import (
    ColumnTypeInfo,
    DataCoordinate,
    DatasetColumnTag,
    DatasetType,
    Dimension,
    DimensionElement,
    DimensionGraph,
    DimensionKeyColumnTag,
    DimensionRecordColumnTag,
    DimensionUniverse,
    LogicalColumn,
    NamedKeyDict,
    NamedValueAbstractSet,
    NamedValueSet,
    SkyPixDimension,
    Timespan,
    TimespanDatabaseRepresentation,
)

# We're not trying to add typing to the lex/yacc parser code, so MyPy
# doesn't know about some of these imports.
from .expressions import make_string_expression_predicate
from .expressions.categorize import categorizeElementOrderByName, categorizeOrderByName


@dataclasses.dataclass(frozen=True, eq=False)
class QueryWhereClause:
    """Structure holding various contributions to a query's WHERE clause.

    Instances of this class should only be created by
    `QueryWhereExpression.combine`, which guarantees the consistency of its
    attributes.
    """

    @classmethod
    def combine(
        cls,
        dimensions: DimensionGraph,
        expression: str = "",
        *,
        bind: Mapping[str, Any] | None = None,
        data_id: DataCoordinate | None = None,
        region: Region | None = None,
        timespan: Timespan | None = None,
        defaults: DataCoordinate | None = None,
        dataset_type_name: str | None = None,
        allow_orphans: bool = False,
    ) -> QueryWhereClause:
        """Construct from various components.

        Parameters
        ----------
        dimensions : `DimensionGraph`
            The dimensions that would be included in the query in the absence
            of the WHERE clause.
        expression : `str`, optional
            A user-provided string expression.
        bind : `Mapping` [ `str`, `object` ], optional
            Mapping containing literal values that should be injected into the
            query expression, keyed by the identifiers they replace.
        data_id : `DataCoordinate`, optional
            A data ID identifying dimensions known in advance.  If not
            provided, will be set to an empty data ID.
        region : `lsst.sphgeom.Region`, optional
            A spatial constraint that all rows must overlap.  If `None` and
            ``data_id`` is an expanded data ID, ``data_id.region`` will be used
            to construct one.
        timespan : `Timespan`, optional
            A temporal constraint that all rows must overlap.  If `None` and
            ``data_id`` is an expanded data ID, ``data_id.timespan`` will be
            used to construct one.
        defaults : `DataCoordinate`, optional
            A data ID containing default for governor dimensions.
        dataset_type_name : `str` or `None`, optional
            The name of the dataset type to assume for unqualified dataset
            columns, or `None` if there are no such identifiers.
        allow_orphans : `bool`, optional
            If `True`, permit expressions to refer to dimensions without
            providing a value for their governor dimensions (e.g. referring to
            a visit without an instrument).  Should be left to default to
            `False` in essentially all new code.

        Returns
        -------
        where : `QueryWhereClause`
            An object representing the WHERE clause for a query.
        """
        if data_id is not None and data_id.hasRecords():
            if region is None and data_id.region is not None:
                region = data_id.region
            if timespan is None and data_id.timespan is not None:
                timespan = data_id.timespan
        if data_id is None:
            data_id = DataCoordinate.makeEmpty(dimensions.universe)
        if defaults is None:
            defaults = DataCoordinate.makeEmpty(dimensions.universe)
        expression_predicate, governor_constraints = make_string_expression_predicate(
            expression,
            dimensions,
            bind=bind,
            data_id=data_id,
            defaults=defaults,
            dataset_type_name=dataset_type_name,
            allow_orphans=allow_orphans,
        )
        return QueryWhereClause(
            expression_predicate,
            data_id,
            region=region,
            timespan=timespan,
            governor_constraints=governor_constraints,
        )

    expression_predicate: Predicate | None
    """A predicate that evaluates a string expression from the user
    (`expressions.Predicate` or `None`).
    """

    data_id: DataCoordinate
    """A data ID identifying dimensions known before query construction
    (`DataCoordinate`).
    """

    region: Region | None
    """A spatial region that all result rows must overlap
    (`lsst.sphgeom.Region` or `None`).
    """

    timespan: Timespan | None
    """A temporal constraint that all result rows must overlap
    (`Timespan` or `None`).
    """

    governor_constraints: Mapping[str, Set[str]]
    """Restrictions on the values governor dimensions can take in this query,
    imposed by the string expression and/or data ID
    (`Mapping` [ `set`,  `~collections.abc.Set` [ `str` ] ]).

    Governor dimensions not present in this mapping are not constrained at all.
    """


@dataclasses.dataclass(frozen=True)
class OrderByClauseColumn:
    """Information about single column in ORDER BY clause."""

    element: DimensionElement
    """Dimension element for data in this column (`DimensionElement`)."""

    column: str | None
    """Name of the column or `None` for primary key (`str` or `None`)"""

    ordering: bool
    """True for ascending order, False for descending (`bool`)."""


@dataclasses.dataclass(frozen=True, eq=False)
class OrderByClause:
    """Class for information about columns in ORDER BY clause"""

    @classmethod
    def parse_general(cls, order_by: Iterable[str], graph: DimensionGraph) -> OrderByClause:
        """Parse an iterable of strings in the context of a multi-dimension
        query.

        Parameters
        ----------
        order_by : `Iterable` [ `str` ]
            Sequence of names to use for ordering with optional "-" prefix.
        graph : `DimensionGraph`
            Dimensions used by a query.

        Returns
        -------
        clause : `OrderByClause`
            New order-by clause representing the given string columns.
        """
        terms = []
        for name in order_by:
            if not name or name == "-":
                raise ValueError("Empty dimension name in ORDER BY")
            ascending = True
            if name[0] == "-":
                ascending = False
                name = name[1:]
            element, column = categorizeOrderByName(graph, name)
            term = cls._make_term(element, column, ascending)
            terms.append(term)
        return cls(terms)

    @classmethod
    def parse_element(cls, order_by: Iterable[str], element: DimensionElement) -> OrderByClause:
        """Parse an iterable of strings in the context of a single dimension
        element query.

        Parameters
        ----------
        order_by : `Iterable` [ `str` ]
            Sequence of names to use for ordering with optional "-" prefix.
        element : `DimensionElement`
            Single or primary dimension element in the query

        Returns
        -------
        clause : `OrderByClause`
            New order-by clause representing the given string columns.
        """
        terms = []
        for name in order_by:
            if not name or name == "-":
                raise ValueError("Empty dimension name in ORDER BY")
            ascending = True
            if name[0] == "-":
                ascending = False
                name = name[1:]
            column = categorizeElementOrderByName(element, name)
            term = cls._make_term(element, column, ascending)
            terms.append(term)
        return cls(terms)

    @classmethod
    def _make_term(cls, element: DimensionElement, column: str | None, ascending: bool) -> SortTerm:
        """Make a single sort term from parsed user expression values.

        Parameters
        ----------
        element : `DimensionElement`
            Dimension element the sort term references.
        column : `str` or `None`
            DimensionRecord field name, or `None` if ``element`` is a
            `Dimension` and the sort term is on is key value.
        ascending : `bool`
            Whether to sort ascending (`True`) or descending (`False`).

        Returns
        -------
        term : `lsst.daf.relation.SortTerm`
            Sort term struct.
        """
        tag: ColumnTag
        expression: ColumnExpression
        if column is None:
            tag = DimensionKeyColumnTag(element.name)
            expression = ColumnExpression.reference(tag)
        elif column in ("timespan.begin", "timespan.end"):
            base_column, _, subfield = column.partition(".")
            tag = DimensionRecordColumnTag(element.name, base_column)
            expression = ColumnExpression.reference(tag).method(
                "lower" if subfield == "begin" else "upper", dtype=astropy.time.Time
            )
        else:
            tag = DimensionRecordColumnTag(element.name, column)
            expression = ColumnExpression.reference(tag)
        return SortTerm(expression, ascending)

    terms: Iterable[SortTerm]
    """Columns that appear in the ORDER BY
    (`Iterable` [ `OrderByClauseColumn` ]).
    """

    @property
    @cached_getter
    def columns_required(self) -> Set[ColumnTag]:
        """Set of column tags for all columns referenced by the ORDER BY clause
        (`~collections.abc.Set` [ `ColumnTag` ]).
        """
        tags: set[ColumnTag] = set()
        for term in self.terms:
            tags.update(term.expression.columns_required)
        return tags


@immutable
class ElementOrderByClause:
    """Class for information about columns in ORDER BY clause for one element.

    Parameters
    ----------
    order_by : `Iterable` [ `str` ]
        Sequence of names to use for ordering with optional "-" prefix.
    element : `DimensionElement`
        Dimensions used by a query.
    """

    def __init__(self, order_by: Iterable[str], element: DimensionElement):

        self.order_by_columns = []
        for name in order_by:
            if not name or name == "-":
                raise ValueError("Empty dimension name in ORDER BY")
            ascending = True
            if name[0] == "-":
                ascending = False
                name = name[1:]
            column = categorizeElementOrderByName(element, name)
            self.order_by_columns.append(
                OrderByClauseColumn(element=element, column=column, ordering=ascending)
            )

    order_by_columns: Iterable[OrderByClauseColumn]
    """Columns that appear in the ORDER BY
    (`Iterable` [ `OrderByClauseColumn` ]).
    """


@immutable
class QuerySummary:
    """A struct that holds and categorizes the dimensions involved in a query.

    A `QuerySummary` instance is necessary to construct a `QueryBuilder`, and
    it needs to include all of the dimensions that will be included in the
    query (including any needed for querying datasets).

    Parameters
    ----------
    requested : `DimensionGraph`
        The dimensions whose primary keys should be included in the result rows
        of the query.
    data_id : `DataCoordinate`, optional
        A fully-expanded data ID identifying dimensions known in advance.  If
        not provided, will be set to an empty data ID.
    expression : `str`, optional
        A user-provided string WHERE expression.
    region : `lsst.sphgeom.Region`, optional
        If `None` and ``data_id`` is an expanded data ID, ``data_id.region``
        will be used to construct one.
    timespan : `Timespan`, optional
        A temporal constraint that all rows must overlap.  If `None` and
        ``data_id`` is an expanded data ID, ``data_id.timespan`` will be used
        to construct one.
    bind : `Mapping` [ `str`, `object` ], optional
        Mapping containing literal values that should be injected into the
        query expression, keyed by the identifiers they replace.
    defaults : `DataCoordinate`, optional
        A data ID containing default for governor dimensions.
    datasets : `Iterable` [ `DatasetType` ], optional
        Dataset types whose searches may be joined into the query.  Callers
        must still call `QueryBuilder.joinDataset` explicitly to control how
        that join happens (e.g. which collections are searched), but by
        declaring them here first we can ensure that the query includes the
        right dimensions for those joins.
    order_by : `Iterable` [ `str` ]
        Sequence of names to use for ordering with optional "-" prefix.
    limit : `Tuple`, optional
        Limit on the number of returned rows and optional offset.
    check : `bool`, optional
        If `False`, permit expressions to refer to dimensions without providing
        a value for their governor dimensions (e.g. referring to a visit
        without an instrument).  Should be left to default to `True` in
        essentially all new code.
    """

    def __init__(
        self,
        requested: DimensionGraph,
        *,
        data_id: DataCoordinate | None = None,
        expression: str = "",
        region: Region | None = None,
        timespan: Timespan | None = None,
        bind: Mapping[str, Any] | None = None,
        defaults: DataCoordinate | None = None,
        datasets: Iterable[DatasetType] = (),
        order_by: Iterable[str] | None = None,
        limit: tuple[int, int | None] | None = None,
        check: bool = True,
    ):
        self.requested = requested
        self.datasets = NamedValueSet(datasets).freeze()
        if len(self.datasets) == 1:
            (dataset_type_name,) = self.datasets.names
        else:
            dataset_type_name = None
        self.where = QueryWhereClause.combine(
            self.requested,
            expression=expression,
            bind=bind,
            data_id=data_id,
            region=region,
            timespan=timespan,
            defaults=defaults,
            dataset_type_name=dataset_type_name,
            allow_orphans=not check,
        )
        self.order_by = None if order_by is None else OrderByClause.parse_general(order_by, requested)
        self.limit = limit
        self.columns_required, self.dimensions = self._compute_columns_required()

    requested: DimensionGraph
    """Dimensions whose primary keys should be included in the result rows of
    the query (`DimensionGraph`).
    """

    where: QueryWhereClause
    """Structure containing objects that contribute to the WHERE clause of the
    query (`QueryWhereClause`).
    """

    datasets: NamedValueAbstractSet[DatasetType]
    """Dataset types whose searches may be joined into the query
    (`NamedValueAbstractSet` [ `DatasetType` ]).
    """

    order_by: OrderByClause | None
    """Object that manages how the query results should be sorted
    (`OrderByClause` or `None`).
    """

    limit: tuple[int, int | None] | None
    """Integer offset and maximum number of rows returned (prior to
    postprocessing filters), respectively.
    """

    dimensions: DimensionGraph
    """All dimensions in the query in any form (`DimensionGraph`).
    """

    columns_required: Set[ColumnTag]
    """All columns that must be included directly in the query.

    This does not include columns that only need to be included in the result
    rows, and hence could be provided by postprocessors.
    """

    @property
    def universe(self) -> DimensionUniverse:
        """All known dimensions (`DimensionUniverse`)."""
        return self.requested.universe

    @property
    @cached_getter
    def spatial(self) -> NamedValueAbstractSet[DimensionElement]:
        """Dimension elements whose regions and skypix IDs should be included
        in the query (`NamedValueAbstractSet` of `DimensionElement`).
        """
        # An element may participate spatially in the query if:
        # - it's the most precise spatial element for its system in the
        #   requested dimensions (i.e. in `self.requested.spatial`);
        # - it isn't also given at query construction time.
        result: NamedValueSet[DimensionElement] = NamedValueSet()
        for family in self.dimensions.spatial:
            element = family.choose(self.dimensions.elements)
            assert isinstance(element, DimensionElement)
            if element not in self.where.data_id.graph.elements:
                result.add(element)
        if len(result) == 1:
            # There's no spatial join, but there might be a WHERE filter based
            # on a given region.
            if self.where.data_id.graph.spatial:
                # We can only perform those filters against SkyPix dimensions,
                # so if what we have isn't one, add the common SkyPix dimension
                # to the query; the element we have will be joined to that.
                (element,) = result
                if not isinstance(element, SkyPixDimension):
                    result.add(self.universe.commonSkyPix)
            else:
                # There is no spatial join or filter in this query.  Even
                # if this element might be associated with spatial
                # information, we don't need it for this query.
                return NamedValueSet().freeze()
        return result.freeze()

    @property
    @cached_getter
    def temporal(self) -> NamedValueAbstractSet[DimensionElement]:
        """Dimension elements whose timespans should be included in the
        query (`NamedValueSet` of `DimensionElement`).
        """
        if len(self.dimensions.temporal) > 1:
            # We don't actually have multiple temporal families in our current
            # dimension configuration, so this limitation should be harmless.
            raise NotImplementedError("Queries that should involve temporal joins are not yet supported.")
        result = NamedValueSet[DimensionElement]()
        if self.where.expression_predicate is not None:
            for tag in DimensionRecordColumnTag.filter_from(self.where.expression_predicate.columns_required):
                if tag.column == "timespan":
                    result.add(self.requested.universe[tag.element])
        return result.freeze()

    def _compute_columns_required(self) -> tuple[set[ColumnTag], DimensionGraph]:
        """Compute the columns that must be provided by the relations joined
        into this query in order to obtain the right *set* of result rows in
        the right order.

        This does not include columns that only need to be included in the
        result rows, and hence could be provided by postprocessors.
        """
        tags: set[ColumnTag] = set(DimensionKeyColumnTag.generate(self.requested.names))
        tags.update(DimensionKeyColumnTag.generate(self.where.data_id.graph.names))
        for dataset_type in self.datasets:
            tags.update(DimensionKeyColumnTag.generate(dataset_type.dimensions.names))
        if self.where.expression_predicate is not None:
            tags.update(self.where.expression_predicate.columns_required)
        if self.order_by is not None:
            tags.update(self.order_by.columns_required)
        # Make sure the dimension keys are expanded self-consistently in what
        # we return by passing them through DimensionGraph.
        dimensions = DimensionGraph(
            self.universe, names={tag.dimension for tag in DimensionKeyColumnTag.filter_from(tags)}
        )
        tags.update(DimensionKeyColumnTag.generate(dimensions.names))
        return (tags, dimensions)


@dataclasses.dataclass
class DatasetQueryColumns:
    """A struct containing the columns used to reconstruct `DatasetRef`
    instances from query results.
    """

    datasetType: DatasetType
    """The dataset type being queried (`DatasetType`).
    """

    id: ColumnElement
    """Column containing the unique integer ID for this dataset.
    """

    runKey: ColumnElement
    """Foreign key column to the `~CollectionType.RUN` collection that holds
    this dataset.
    """

    ingestDate: ColumnElement | None
    """Column containing the ingest timestamp, this is not a part of
    `DatasetRef` but it comes from the same table.
    """

    def __iter__(self) -> Iterator[ColumnElement]:
        yield self.id
        yield self.runKey


@dataclasses.dataclass
class QueryColumns:
    """A struct organizing the columns in an under-construction or currently-
    executing query.

    Takes no parameters at construction, as expected usage is to add elements
    to its container attributes incrementally.
    """

    def __init__(self) -> None:
        self.keys = NamedKeyDict()
        self.timespans = NamedKeyDict()
        self.regions = NamedKeyDict()
        self.datasets = None

    keys: NamedKeyDict[Dimension, list[ColumnElement]]
    """Columns that correspond to the primary key values of dimensions
    (`NamedKeyDict` mapping `Dimension` to a `list` of `ColumnElement`).

    Each value list contains columns from multiple tables corresponding to the
    same dimension, and the query should constrain the values of those columns
    to be the same.

    In a `Query`, the keys of this dictionary must include at least the
    dimensions in `QuerySummary.requested` and `QuerySummary.data_id.graph`.
    """

    timespans: NamedKeyDict[DimensionElement, TimespanDatabaseRepresentation]
    """Columns that correspond to timespans for elements that participate in a
    temporal join or filter in the query (`NamedKeyDict` mapping
    `DimensionElement` to `TimespanDatabaseRepresentation`).

    In a `Query`, the keys of this dictionary must be exactly the elements
    in `QuerySummary.temporal`.
    """

    regions: NamedKeyDict[DimensionElement, ColumnElement]
    """Columns that correspond to regions for elements that participate in a
    spatial join or filter in the query (`NamedKeyDict` mapping
    `DimensionElement` to `sqlalchemy.sql.ColumnElement`).

    In a `Query`, the keys of this dictionary must be exactly the elements
    in `QuerySummary.spatial`.
    """

    datasets: DatasetQueryColumns | None
    """Columns that can be used to construct `DatasetRef` instances from query
    results.
    (`DatasetQueryColumns` or `None`).
    """

    def isEmpty(self) -> bool:
        """Return `True` if this query has no columns at all."""
        return not (self.keys or self.timespans or self.regions or self.datasets is not None)

    def getKeyColumn(self, dimension: Dimension | str) -> ColumnElement:
        """Return one of the columns in self.keys for the given dimension.

        The column selected is an implentation detail but is guaranteed to
        be deterministic and consistent across multiple calls.

        Parameters
        ----------
        dimension : `Dimension` or `str`
            Dimension for which to obtain a key column.

        Returns
        -------
        column : `sqlalchemy.sql.ColumnElement`
            SQLAlchemy column object.
        """
        # Choosing the last element here is entirely for human readers of the
        # query (e.g. developers debugging things); it makes it more likely a
        # dimension key will be provided by the dimension's own table, or
        # failing that, some closely related dimension, which might be less
        # surprising to see than e.g. some dataset subquery.  From the
        # database's perspective this is entirely arbitrary, because the query
        # guarantees they all have equal values.
        return self.keys[dimension][-1]

    def make_logical_column_mapping(self) -> dict[ColumnTag, LogicalColumn]:
        """Create a dictionary with `ColumnTag` keys for the columns
        tracked by this object.

        This is a transitional method that converts from the old way of
        representing columns in queries (this class) to the new one (containers
        involving `ColumnTag`).
        """
        result: dict[ColumnTag, LogicalColumn] = {}
        for dimension in self.keys:
            result[DimensionKeyColumnTag(dimension.name)] = self.getKeyColumn(dimension)
        for element, region_column in self.regions.items():
            result[DimensionRecordColumnTag(element.name, "region")] = region_column
        for element, timespan_column in self.timespans.items():
            result[DimensionRecordColumnTag(element.name, "timespan")] = timespan_column
        if self.datasets is not None:
            dataset_type_name = self.datasets.datasetType.name
            result[DatasetColumnTag(dataset_type_name, "dataset_id")] = self.datasets.id
            result[DatasetColumnTag(dataset_type_name, "run")] = self.datasets.runKey
            if self.datasets.ingestDate is not None:
                result[DatasetColumnTag(dataset_type_name, "ingest_date")] = self.datasets.ingestDate
        return result

    @staticmethod
    def from_logical_columns(
        logical_columns: Mapping[ColumnTag, LogicalColumn],
        dataset_types: NamedValueAbstractSet[DatasetType],
        column_types: ColumnTypeInfo,
    ) -> QueryColumns:
        """Create a `QueryColumns` instance from a mapping keyed by
        `sql.ColumnTag`.

        This is a transitional method that converts from the new way of
        representing columns in queries to this old one.

        Parameters
        ----------
        logical_columns : `Mapping` [ `ColumnTag`, `LogicalColumn` ]
            Mapping of columns to convert.
        dataset_types : `NamedValueAbstractSet` [ `DatasetType` ]
            Set of all dataset types participating in the query.
        column_types : `ColumnTypeInfo`
            Information about column types that can vary between data
            repositories.

        Returns
        -------
        columns : `QueryColumns`
            Translated `QueryColumns` instance.
        """
        result = QueryColumns()
        dataset_kwargs: dict[str, Any] = {}
        for tag in logical_columns.keys():
            match tag:
                case DimensionKeyColumnTag(dimension=dimension_name):
                    dimension = cast(Dimension, column_types.universe[dimension_name])
                    result.keys[dimension] = [cast(ColumnElement, logical_columns[tag])]
                case DimensionRecordColumnTag(element=element_name, column="timespan"):
                    element = column_types.universe[element_name]
                    result.timespans[element] = cast(TimespanDatabaseRepresentation, logical_columns[tag])
                case DimensionRecordColumnTag(element=element_name, column="region"):
                    element = column_types.universe[element_name]
                    result.regions[element] = cast(ColumnElement, logical_columns[tag])
                case DatasetColumnTag(dataset_type=dataset_type_name, column=column_name):
                    dataset_type = dataset_types[dataset_type_name]
                    old_dataset_type = dataset_kwargs.setdefault("datasetType", dataset_type)
                    assert old_dataset_type == dataset_type, "Queries can only have one result dataset type."
                    match column_name:
                        case "dataset_id":
                            dataset_kwargs["id"] = cast(ColumnElement, logical_columns[tag])
                        case "run":
                            dataset_kwargs["runKey"] = cast(ColumnElement, logical_columns[tag])
                        case "ingest_date":
                            dataset_kwargs["ingestDate"] = cast(ColumnElement, logical_columns[tag])
        if dataset_kwargs:
            result.datasets = DatasetQueryColumns(**dataset_kwargs)
        return result
