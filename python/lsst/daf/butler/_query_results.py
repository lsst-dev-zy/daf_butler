# This file is part of daf_butler.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This software is dual licensed under the GNU General Public License and also
# under a 3-clause BSD license. Recipients may choose which of these licenses
# to use; please see the files gpl-3.0.txt and/or bsd_license.txt,
# respectively.  If you choose the GPL option then the following text applies
# (but note that there is still no warranty even if you opt for BSD instead):
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

__all__ = (
    "DataCoordinateQueryResults",
    "DatasetQueryResults",
    "DimensionRecordQueryResults",
    "ParentDatasetQueryResults",
)

from abc import abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from ._dataset_ref import DatasetRef
from .dimensions import DataCoordinate, DimensionRecord

if TYPE_CHECKING:
    from ._dataset_type import DatasetType
    from .dimensions import DimensionElement, DimensionGroup


class DataCoordinateQueryResults(Iterable[DataCoordinate]):
    """An interface for objects that represent the results of queries for
    data IDs.
    """

    @property
    @abstractmethod
    def dimensions(self) -> DimensionGroup:
        """The dimensions of the data IDs returned by this query."""
        raise NotImplementedError()

    @abstractmethod
    def has_full(self) -> bool:
        """Indicate if all data IDs in this iterable identify all dimensions,
        not just required dimensions.

        Returns
        -------
        state : `bool`
            If `True`, ``all(d.hasFull() for d in self)`` is guaranteed.
            If `False`, no guarantees are made.
        """
        raise NotImplementedError()

    @abstractmethod
    def has_records(self) -> bool:
        """Return whether all data IDs in this iterable contain records.

        Returns
        -------
        state : `bool`
            If `True`, ``all(d.hasRecords() for d in self)`` is guaranteed.
            If `False`, no guarantees are made.
        """
        raise NotImplementedError()

    @abstractmethod
    def materialize(self) -> AbstractContextManager[DataCoordinateQueryResults]:
        """Insert this query's results into a temporary table.

        Returns
        -------
        context : `typing.ContextManager` [ `DataCoordinateQueryResults` ]
            A context manager that ensures the temporary table is created and
            populated in ``__enter__`` (returning a results object backed by
            that table), and dropped in ``__exit__``.  If ``self`` is already
            materialized, the context manager may do nothing (reflecting the
            fact that an outer context manager should already take care of
            everything else).

        Notes
        -----
        When using a very large result set to perform multiple queries (e.g.
        multiple calls to `subset` with different arguments, or even a single
        call to `expanded`), it may be much more efficient to start by
        materializing the query and only then performing the follow up queries.
        It may also be less efficient, depending on how well database engine's
        query optimizer can simplify those particular follow-up queries and
        how efficiently it caches query results even when the are not
        explicitly inserted into a temporary table.  See `expanded` and
        `subset` for examples.
        """
        raise NotImplementedError()

    @abstractmethod
    def expanded(self) -> DataCoordinateQueryResults:
        """Return a results object for which `has_records` returns `True`.

        This method may involve actually executing database queries to fetch
        `DimensionRecord` objects.

        Returns
        -------
        results : `DataCoordinateQueryResults`
            A results object for which `has_records` returns `True`.  May be
            ``self`` if that is already the case.

        Notes
        -----
        For very result sets, it may be much more efficient to call
        `materialize` before calling `expanded`, to avoid performing the
        original query multiple times (as a subquery) in the follow-up queries
        that fetch dimension records.  For example::

            with butler.query() as query:
                with query.data_ids(...).materialize() as tempDataIds:
                    dataIdsWithRecords = tempDataIds.expanded()
                    for dataId in dataIdsWithRecords:
                        ...
        """
        raise NotImplementedError()

    @abstractmethod
    def subset(
        self,
        dimensions: DimensionGroup | Iterable[str] | None = None,
        *,
        unique: bool = False,
    ) -> DataCoordinateQueryResults:
        """Return a results object containing a subset of the dimensions of
        this one, and/or a unique near-subset of its rows.

        This method may involve actually executing database queries to fetch
        `DimensionRecord` objects.

        Parameters
        ----------
        dimensions : `DimensionGroup` or \
                `~collections.abc.Iterable` [ `str`], optional
            Dimensions to include in the new results object.  If `None`,
            ``self.dimensions`` is used.
        unique : `bool`, optional
            If `True` (`False` is default), the query should only return unique
            data IDs.  This is implemented in the database; to obtain unique
            results via Python-side processing (which may be more efficient in
            some cases), use `toSet` to construct a `DataCoordinateSet` from
            this results object instead.

        Returns
        -------
        results : `DataCoordinateQueryResults`
            A results object corresponding to the given criteria.  May be
            ``self`` if it already qualifies.

        Raises
        ------
        ValueError
            Raised when ``dimensions`` is not a subset of the dimensions in
            this result.

        Notes
        -----
        This method can only return a "near-subset" of the original result rows
        in general because of subtleties in how spatial overlaps are
        implemented; see `Query.projected` for more information.

        When calling `subset` multiple times on the same very large result set,
        it may be much more efficient to call `materialize` first.  For
        example::

            dimensions1 = DimensionGroup(...)
            dimensions2 = DimensionGroup(...)
            with butler.query(...)as query:
                with query.data_ids(...).materialize() as data_ids:
                    for dataId1 in data_ids.subset(dimensions1, unique=True):
                        ...
                    for dataId2 in data_ids.subset(dimensions2, unique=True):
                        ...
        """
        raise NotImplementedError()

    @abstractmethod
    def find_datasets(
        self, dataset_type: DatasetType | str, collections: Any, *, find_first: bool = True
    ) -> DatasetQueryResults:
        """Find datasets using the data IDs identified by this query.

        Parameters
        ----------
        dataset_type : `DatasetType` or `str`
            Dataset type or the name of one to search for.  Must have
            dimensions that are a subset of ``self.dimensions``.
        collections : `Any`
            An expression that fully or partially identifies the collections
            to search for the dataset, such as a `str`, `re.Pattern`, or
            iterable  thereof.  ``...`` can be used to return all collections.
            See :ref:`daf_butler_collection_expressions` for more information.
        find_first : `bool`, optional
            If `True` (default), for each result data ID, only yield one
            `DatasetRef`, from the first collection in which a dataset of that
            dataset type appears (according to the order of ``collections``
            passed in).  If `True`, ``collections`` must not contain regular
            expressions and may not be ``...``.

        Returns
        -------
        datasets : `ParentDatasetQueryResults`
            A lazy-evaluation object representing dataset query results,
            iterable over `DatasetRef` objects.  If ``self.has_records()``, all
            nested data IDs in those dataset references will have records as
            well.

        Raises
        ------
        MissingDatasetTypeError
            Raised if the given dataset type is not registered.
        """
        raise NotImplementedError()

    @abstractmethod
    def find_related_datasets(
        self,
        dataset_type: DatasetType | str,
        collections: Any,
        *,
        find_first: bool = True,
        dimensions: DimensionGroup | Iterable[str] | None = None,
    ) -> Iterable[tuple[DataCoordinate, DatasetRef]]:
        """Find datasets using the data IDs identified by this query, and
        return them along with the original data IDs.

        This is a variant of `find_datasets` that is often more useful when
        the target dataset type does not have all of the dimensions of the
        original data ID query, as is generally the case with calibration
        lookups.

        Parameters
        ----------
        dataset_type : `DatasetType` or `str`
            Dataset type or the name of one to search for.  Must have
            dimensions that are a subset of ``self.dimensions``.
        collections : `Any`
            An expression that fully or partially identifies the collections
            to search for the dataset, such as a `str`, `re.Pattern`, or
            iterable  thereof.  ``...`` can be used to return all collections.
            See :ref:`daf_butler_collection_expressions` for more information.
        find_first : `bool`, optional
            If `True` (default), for each data ID in ``self``, only yield one
            `DatasetRef`, from the first collection in which a dataset of that
            dataset type appears (according to the order of ``collections``
            passed in).  If `True`, ``collections`` must not contain regular
            expressions and may not be ``...``.  Note that this is not the
            same as yielding one `DatasetRef` for each yielded data ID if
            ``dimensions`` is not `None`.
        dimensions : `DimensionGroup`, or \
                `~collections.abc.Iterable` [ `str` ], optional
            The dimensions of the data IDs returned.  Must be a subset of
            ``self.dimensions``.

        Returns
        -------
        pairs : `~collections.abc.Iterable` [ `tuple` [ `DataCoordinate`, \
                `DatasetRef` ] ]
            An iterable of (data ID, dataset reference) pairs.

        Raises
        ------
        MissingDatasetTypeError
            Raised if the given dataset type is not registered.
        """
        raise NotImplementedError()

    @abstractmethod
    def count(self, *, exact: bool = True, discard: bool = False) -> int:
        """Count the number of rows this query would return.

        Parameters
        ----------
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed to account for that filtering in the count.  If `False`, the
            result may be an upper bound.
        discard : `bool`, optional
            If `True`, compute the exact count even if it would require running
            the full query and then throwing away the result rows after
            counting them.  If `False`, this is an error, as the user would
            usually be better off executing the query first to fetch its rows
            into a new query (or passing ``exact=False``).  Ignored if
            ``exact=False``.

        Returns
        -------
        count : `int`
            The number of rows the query would return, or an upper bound if
            ``exact=False``.

        Notes
        -----
        This counts the number of rows returned, not the number of unique rows
        returned, so even with ``exact=True`` it may provide only an upper
        bound on the number of *deduplicated* result rows.
        """
        raise NotImplementedError()

    @abstractmethod
    def any(self, *, execute: bool = True, exact: bool = True) -> bool:
        """Test whether this query returns any results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True`, execute at least a ``LIMIT 1`` query if it cannot be
            determined prior to execution that the query would return no rows.
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed, until at least one result row is found.  If `False`, the
            returned result does not account for post-query filtering, and
            hence may be `True` even when all result rows would be filtered
            out.

        Returns
        -------
        any : `bool`
            `True` if the query would (or might, depending on arguments) yield
            result rows.  `False` if it definitely would not.
        """
        raise NotImplementedError()

    @abstractmethod
    def explain_no_results(self, execute: bool = True) -> Iterable[str]:
        """Return human-readable messages that may help explain why the query
        yields no results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True` (default) execute simplified versions (e.g. ``LIMIT 1``)
            of aspects of the tree to more precisely determine where rows were
            filtered out.

        Returns
        -------
        messages : `~collections.abc.Iterable` [ `str` ]
            String messages that describe reasons the query might not yield any
            results.
        """
        raise NotImplementedError()

    @abstractmethod
    def order_by(self, *args: str) -> DataCoordinateQueryResults:
        """Make the iterator return ordered results.

        Parameters
        ----------
        *args : `str`
            Names of the columns/dimensions to use for ordering. Column name
            can be prefixed with minus (``-``) to use descending ordering.

        Returns
        -------
        result : `DataCoordinateQueryResults`
            Returns ``self`` instance which is updated to return ordered
            result.

        Notes
        -----
        This method modifies the iterator in place and returns the same
        instance to support method chaining.
        """
        raise NotImplementedError()

    @abstractmethod
    def limit(self, limit: int, offset: int | None = 0) -> DataCoordinateQueryResults:
        """Make the iterator return limited number of records.

        Parameters
        ----------
        limit : `int`
            Upper limit on the number of returned records.
        offset : `int` or `None`, optional
            The number of records to skip before returning at most ``limit``
            records.  `None` is interpreted the same as zero for backwards
            compatibility.

        Returns
        -------
        result : `DataCoordinateQueryResults`
            Returns ``self`` instance which is updated to return limited set
            of records.

        Notes
        -----
        This method modifies the iterator in place and returns the same
        instance to support method chaining. Normally this method is used
        together with `order_by` method.
        """
        raise NotImplementedError()


class DatasetQueryResults(Iterable[DatasetRef]):
    """An interface for objects that represent the results of queries for
    datasets.
    """

    @abstractmethod
    def by_parent_dataset_type(self) -> Iterator[ParentDatasetQueryResults]:
        """Group results by parent dataset type.

        Returns
        -------
        iter : `~collections.abc.Iterator` [ `ParentDatasetQueryResults` ]
            An iterator over `DatasetQueryResults` instances that are each
            responsible for a single parent dataset type (either just that
            dataset type, one or more of its component dataset types, or both).
        """
        raise NotImplementedError()

    @abstractmethod
    def materialize(self) -> AbstractContextManager[DatasetQueryResults]:
        """Insert this query's results into a temporary table.

        Returns
        -------
        context : `typing.ContextManager` [ `DatasetQueryResults` ]
            A context manager that ensures the temporary table is created and
            populated in ``__enter__`` (returning a results object backed by
            that table), and dropped in ``__exit__``.  If ``self`` is already
            materialized, the context manager may do nothing (reflecting the
            fact that an outer context manager should already take care of
            everything else).
        """
        raise NotImplementedError()

    @abstractmethod
    def expanded(self) -> DatasetQueryResults:
        """Return a `DatasetQueryResults` for which `DataCoordinate.hasRecords`
        returns `True` for all data IDs in returned `DatasetRef` objects.

        Returns
        -------
        expanded : `DatasetQueryResults`
            Either a new `DatasetQueryResults` instance or ``self``, if it is
            already expanded.

        Notes
        -----
        As with `DataCoordinateQueryResults.expanded`, it may be more efficient
        to call `materialize` before expanding data IDs for very large result
        sets.
        """
        raise NotImplementedError()

    @abstractmethod
    def count(self, *, exact: bool = True, discard: bool = False) -> int:
        """Count the number of rows this query would return.

        Parameters
        ----------
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed to account for that filtering in the count.  If `False`, the
            result may be an upper bound.
        discard : `bool`, optional
            If `True`, compute the exact count even if it would require running
            the full query and then throwing away the result rows after
            counting them.  If `False`, this is an error, as the user would
            usually be better off executing the query first to fetch its rows
            into a new query (or passing ``exact=False``).  Ignored if
            ``exact=False``.

        Returns
        -------
        count : `int`
            The number of rows the query would return, or an upper bound if
            ``exact=False``.

        Notes
        -----
        This counts the number of rows returned, not the number of unique rows
        returned, so even with ``exact=True`` it may provide only an upper
        bound on the number of *deduplicated* result rows.
        """
        raise NotImplementedError()

    @abstractmethod
    def any(self, *, execute: bool = True, exact: bool = True) -> bool:
        """Test whether this query returns any results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True`, execute at least a ``LIMIT 1`` query if it cannot be
            determined prior to execution that the query would return no rows.
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed, until at least one result row is found.  If `False`, the
            returned result does not account for post-query filtering, and
            hence may be `True` even when all result rows would be filtered
            out.

        Returns
        -------
        any : `bool`
            `True` if the query would (or might, depending on arguments) yield
            result rows.  `False` if it definitely would not.
        """
        raise NotImplementedError()

    @abstractmethod
    def explain_no_results(self, execute: bool = True) -> Iterable[str]:
        """Return human-readable messages that may help explain why the query
        yields no results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True` (default) execute simplified versions (e.g. ``LIMIT 1``)
            of aspects of the tree to more precisely determine where rows were
            filtered out.

        Returns
        -------
        messages : `~collections.abc.Iterable` [ `str` ]
            String messages that describe reasons the query might not yield any
            results.
        """
        raise NotImplementedError()


class ParentDatasetQueryResults(DatasetQueryResults):
    """An object that represents results from a query for datasets with a
    single parent `DatasetType`.
    """

    @abstractmethod
    def materialize(self) -> AbstractContextManager[ParentDatasetQueryResults]:
        # Docstring inherited from DatasetQueryResults.
        raise NotImplementedError()

    @property
    @abstractmethod
    def parent_dataset_type(self) -> DatasetType:
        """The parent dataset type for all datasets in this iterable
        (`DatasetType`).
        """
        raise NotImplementedError()

    @property
    @abstractmethod
    def data_ids(self) -> DataCoordinateQueryResults:
        """A lazy-evaluation object representing a query for just the data
        IDs of the datasets that would be returned by this query
        (`DataCoordinateQueryResults`).

        The returned object is not in general `zip`-iterable with ``self``;
        it may be in a different order or have (or not have) duplicates.
        """
        raise NotImplementedError()

    @abstractmethod
    def with_components(self, components: Sequence[str | None]) -> ParentDatasetQueryResults:
        """Return a new query results object for the same parent datasets but
        different components.

        Parameters
        ----------
        components : `~collections.abc.Sequence` [ `str` or `None` ]
            Names of components to include in iteration.  `None` may be
            included (at most once) to include the parent dataset type.
        """
        raise NotImplementedError()

    def expanded(self) -> ParentDatasetQueryResults:
        # Docstring inherited from DatasetQueryResults.
        raise NotImplementedError()


class DimensionRecordQueryResults(Iterable[DimensionRecord]):
    """An interface for objects that represent the results of queries for
    dimension records.
    """

    @property
    @abstractmethod
    def element(self) -> DimensionElement:
        """Dimension element for this result (`DimensionElement`)."""
        raise NotImplementedError()

    @abstractmethod
    def run(self) -> DimensionRecordQueryResults:
        """Execute the query and return an instance with data held in memory.

        Returns
        -------
        result : `DimensionRecordQueryResults`
            Query results, may return ``self`` if it has all data in memory
            already.
        """
        raise NotImplementedError()

    @abstractmethod
    def count(self, *, exact: bool = True, discard: bool = False) -> int:
        """Count the number of rows this query would return.

        Parameters
        ----------
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed to account for that filtering in the count.  If `False`, the
            result may be an upper bound.
        discard : `bool`, optional
            If `True`, compute the exact count even if it would require running
            the full query and then throwing away the result rows after
            counting them.  If `False`, this is an error, as the user would
            usually be better off executing the query first to fetch its rows
            into a new query (or passing ``exact=False``).  Ignored if
            ``exact=False``.

        Returns
        -------
        count : `int`
            The number of rows the query would return, or an upper bound if
            ``exact=False``.

        Notes
        -----
        This counts the number of rows returned, not the number of unique rows
        returned, so even with ``exact=True`` it may provide only an upper
        bound on the number of *deduplicated* result rows.
        """
        raise NotImplementedError()

    @abstractmethod
    def any(self, *, execute: bool = True, exact: bool = True) -> bool:
        """Test whether this query returns any results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True`, execute at least a ``LIMIT 1`` query if it cannot be
            determined prior to execution that the query would return no rows.
        exact : `bool`, optional
            If `True`, run the full query and perform post-query filtering if
            needed, until at least one result row is found.  If `False`, the
            returned result does not account for post-query filtering, and
            hence may be `True` even when all result rows would be filtered
            out.

        Returns
        -------
        any : `bool`
            `True` if the query would (or might, depending on arguments) yield
            result rows.  `False` if it definitely would not.
        """
        raise NotImplementedError()

    @abstractmethod
    def order_by(self, *args: str) -> DimensionRecordQueryResults:
        """Make the iterator return ordered result.

        Parameters
        ----------
        *args : `str`
            Names of the columns/dimensions to use for ordering. Column name
            can be prefixed with minus (``-``) to use descending ordering.

        Returns
        -------
        result : `DimensionRecordQueryResults`
            Returns ``self`` instance which is updated to return ordered
            result.

        Notes
        -----
        This method can modify the iterator in place and return the same
        instance.
        """
        raise NotImplementedError()

    @abstractmethod
    def limit(self, limit: int, offset: int | None = 0) -> DimensionRecordQueryResults:
        """Make the iterator return limited number of records.

        Parameters
        ----------
        limit : `int`
            Upper limit on the number of returned records.
        offset : `int` or `None`
            The number of records to skip before returning at most ``limit``
            records.  `None` is interpreted the same as zero for backwards
            compatibility.

        Returns
        -------
        result : `DimensionRecordQueryResults`
            Returns ``self`` instance which is updated to return limited set of
            records.

        Notes
        -----
        This method can modify the iterator in place and return the same
        instance. Normally this method is used together with `order_by` method.
        """
        raise NotImplementedError()

    @abstractmethod
    def explain_no_results(self, execute: bool = True) -> Iterable[str]:
        """Return human-readable messages that may help explain why the query
        yields no results.

        Parameters
        ----------
        execute : `bool`, optional
            If `True` (default) execute simplified versions (e.g. ``LIMIT 1``)
            of aspects of the tree to more precisely determine where rows were
            filtered out.

        Returns
        -------
        messages : `~collections.abc.Iterable` [ `str` ]
            String messages that describe reasons the query might not yield any
            results.
        """
        raise NotImplementedError()