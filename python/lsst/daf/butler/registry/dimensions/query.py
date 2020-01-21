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

__all__ = ["QueryDimensionRecordStorage"]

from typing import Optional

import sqlalchemy

from ...core import DataCoordinate, Dimension, DimensionElement, DimensionRecord, Timespan
from ...core.dimensions.schema import makeElementTableSpec
from ...core.utils import NamedKeyDict
from ..interfaces import Database, DimensionRecordStorage
from ..queries import QueryBuilder


class QueryDimensionRecordStorage(DimensionRecordStorage):
    """A read-only record storage implementation backed by SELECT query.

    At present, the only query this class supports is a SELECT DISTNCT over the
    table for some other dimension that has this dimension as an implied
    dependency.  For example, we can use this class to provide access to the
    set of ``abstract_filter`` names referenced by any ``physical_filter``.

    Parameters
    ----------
    db : `Database`
        Interface to the database engine and namespace that will hold these
        dimension records.
    element : `DimensionElement`
        The element whose records this storage will manage.
    """
    def __init__(self, db: Database, element: DimensionElement):
        self._db = db
        self._element = element
        self._target = element.universe[element.viewOf]
        self._targetSpec = makeElementTableSpec(self._target)
        self._query = None  # Constructed on first use.
        if element not in self._target.graph.dimensions:
            raise NotImplementedError("Query-backed dimension must be a dependency of its target.")
        assert isinstance(element, Dimension), "An element cannot be a dependency unless it is a dimension."
        if element.metadata:
            raise NotImplementedError("Cannot use query to back dimension with metadata.")
        if element.implied:
            raise NotImplementedError("Cannot use query to back dimension with implied dependencies.")
        if element.alternateKeys:
            raise NotImplementedError("Cannot use query to back dimension with alternate unique keys.")
        if element.spatial:
            raise NotImplementedError("Cannot use query to back spatial dimension.")
        if element.temporal:
            raise NotImplementedError("Cannot use query to back temporal dimension.")

    @property
    def element(self) -> DimensionElement:
        # Docstring inherited from DimensionRecordStorage.element.
        return self._element

    def clearCaches(self):
        # Docstring inherited from DimensionRecordStorage.clearCaches.
        pass

    def _ensureQuery(self):
        if self._query is None:
            targetTable = self._db.getExistingTable(self._target.name, self._targetSpec)
            columns = []
            # The only columns for this dimension are ones for its required
            # dependencies and its own primary key (guaranteed by the checks in
            # the ctor).
            for dimension in self.element.graph.required:
                if dimension == self.element:
                    columns.append(targetTable.columns[dimension.name].label(dimension.primaryKey.name))
                else:
                    columns.append(targetTable.columns[dimension.name].label(dimension.name))
            # This query doesn't do a SELECT DISTINCT, because that's confusing
            # and potentially wasteful if we apply a restrictive WHERE clause,
            # as SelectableDimensionRecordStorage.fetch will do.
            # Instead, we add DISTINCT in join() only.
            self._query = sqlalchemy.sql.select(
                columns, distinct=True
            ).select_from(
                targetTable
            ).alias(
                self.element.name
            )

    def getElementTable(self, dataId: Optional[DataId] = None) -> Optional[sqlalchemy.sql.FromClause]:
        self._ensureQuery()
        return self._query

    def getCommonSkyPixOverlapTable(self, dataId: Optional[DataId] = None
                                    ) -> Optional[sqlalchemy.sql.FromClause]:
        return None

    def insert(self, *records: DimensionRecord):
        # Docstring inherited from DimensionRecordStorage.insert.
        raise TypeError(f"Cannot insert {self.element.name} records.")

    def fetch(self, dataId: DataCoordinate) -> Optional[DimensionRecord]:
        # Docstring inherited from DimensionRecordStorage.fetch.
        RecordClass = self.element.RecordClass
        # Given the restrictions imposed at construction, we know there's
        # nothing to actually fetch: everything we need is in the data ID.
        return RecordClass.fromDict(dataId)
