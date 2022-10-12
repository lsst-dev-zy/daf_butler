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

__all__ = ["PgSphereObsCorePlugin"]

import warnings
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Optional, Tuple

import sqlalchemy
from lsst.daf.butler import DatasetId
from lsst.sphgeom import ConvexPolygon, LonLat, Region
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType

from ...core import ddl
from ._spatial import MissingDatabaseError, RegionTypeWarning, SpatialObsCorePlugin

if TYPE_CHECKING:
    from ..interfaces import Database, StaticTablesContext
    from ._records import Record
    from ._schema import ObsCoreSchema


class PgSpherePoint(UserDefinedType):
    """SQLAlchemy type representing pgSphere point (spoint) type.

    On Python side this type corresponds to `lsst.sphgeom.LonLat`.
    Only a limited set of methods is implemented, sufficient to store the
    data in the database.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        """Return name of the column type"""
        return "SPOINT"

    def bind_processor(self, dialect: sqlalchemy.engine.Dialect) -> Callable:
        """Return processor method for bind values"""

        def _process(value: LonLat) -> str:
            lon = value.getLon().asRadians()
            lat = value.getLat().asRadians()
            return f"({lon},{lat})"

        return _process


class PgSpherePolygon(UserDefinedType):
    """SQLAlchemy type representing pgSphere polygon (spoly) type.

    On Python side it corresponds to a sequence of `lsst.sphgeom.LonLat`
    instances (sphgeom polygons are convex, while pgSphere polygons do not
    have to be). Only a limited set of methods is implemented, sufficient to
    store the data in the database.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        """Return name of the column type"""
        return "SPOLY"

    def bind_processor(self, dialect: sqlalchemy.engine.Dialect) -> Callable:
        """Return processor method for bind values"""

        def _process(value: Sequence[LonLat]) -> str:
            points = []
            for lonlat in value:
                lon = lonlat.getLon().asRadians()
                lat = lonlat.getLat().asRadians()
                points.append(f"({lon},{lat})")
            return "{" + ",".join(points) + "}"

        return _process


# To suppress SAWarning about unknown types we need to make them known, this
# is not explicitly documented but it is what other people do.
ischema_names["spoint"] = PgSpherePoint
ischema_names["spoly"] = PgSpherePolygon


class PgSphereObsCorePlugin(SpatialObsCorePlugin):
    """Spatial ObsCore plugin which creates pg_sphere geometries.

    This plugin adds and fills two columns to obscore table - one for the
    region (polygon), another for the position of the center of bounding
    circle. Both columns are indexed. Column names can be changed via plugin
    configuration.
    """

    def __init__(self, *, name: str, config: Mapping[str, Any]):
        self._name = name
        self._region_column_name = config.get("region_column", "pgsphere_region")
        self._position_column_name = config.get("position_column", "pgsphere_position")

    @classmethod
    def initialize(
        cls, *, name: str, config: Mapping[str, Any], db: Optional[Database]
    ) -> SpatialObsCorePlugin:
        # docstring inherited.

        if db is None:
            raise MissingDatabaseError("Database access is required for pgSphere plugin")

        # Check that engine is Postgres and pgSphere extension is enabled.
        if db.dialect.name != "postgresql":
            raise RuntimeError("PgSphere spatial plugin for obscore requires PostgreSQL database.")
        query = "SELECT COUNT(*) FROM pg_extension WHERE extname='pg_sphere'"
        result = db.query(sqlalchemy.sql.text(query))
        if result.scalar() == 0:
            raise RuntimeError(
                "PgSphere spatial plugin for obscore requires the pgSphere extension. "
                "Please run `CREATE EXTENSION pg_sphere;` on a database containing obscore table "
                "from a PostgreSQL superuser account."
            )

        return cls(name=name, config=config)

    def extend_table_spec(self, table_spec: ddl.TableSpec) -> None:
        # docstring inherited.
        table_spec.fields.update(
            (
                ddl.FieldSpec(
                    name=self._region_column_name,
                    dtype=PgSpherePolygon,
                    doc="pgSphere polygon for this record region.",
                ),
                ddl.FieldSpec(
                    name=self._position_column_name,
                    dtype=PgSpherePoint,
                    doc="pgSphere position for this record, center of bounding circle.",
                ),
            )
        )
        # Spatial columns need GIST index type
        table_spec.indexes.add(ddl.IndexSpec(self._region_column_name, postgresql_using="gist"))
        table_spec.indexes.add(ddl.IndexSpec(self._position_column_name, postgresql_using="gist"))

    def make_extra_tables(self, schema: ObsCoreSchema, context: StaticTablesContext) -> None:
        # docstring inherited.
        return

    def make_records(
        self, dataset_id: DatasetId, region: Optional[Region]
    ) -> Tuple[Optional[Record], Optional[Mapping[sqlalchemy.schema.Table, Sequence[Record]]]]:
        # docstring inherited.

        if region is None:
            return None, None

        record: Record = {}
        circle = region.getBoundingCircle()
        record[self._position_column_name] = LonLat(circle.getCenter())

        # Presently we can only handle polygons
        if isinstance(region, ConvexPolygon):
            poly_points = [LonLat(vertex) for vertex in region.getVertices()]
            record[self._region_column_name] = poly_points
        else:
            warnings.warn(
                f"Unexpected region type for obscore dataset {dataset_id}: {type(region)}",
                category=RegionTypeWarning,
            )

        return record, None
