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

__all__ = ("RegistryConfig",)

from typing import Optional, Type, TYPE_CHECKING, Union

from lsst.utils import doImportType

from ..core import ConfigSubset
from ..core.repoRelocation import replaceRoot
from .connectionString import ConnectionStringFactory
from .interfaces import Database

if TYPE_CHECKING:
    import sqlalchemy
    from ..core import ButlerURI


class RegistryConfig(ConfigSubset):
    component = "registry"
    requiredKeys = ("db",)
    defaultConfigFile = "registry.yaml"

    def getDialect(self) -> str:
        """Parses the `db` key of the config and returns the database dialect.

        Returns
        -------
        dialect : `str`
            Dialect found in the connection string.
        """
        conStr = ConnectionStringFactory.fromConfig(self)
        return conStr.get_backend_name()

    def getDatabaseClass(self) -> Type[Database]:
        """Returns the `Database` class targeted by configuration values.

        The appropriate class is determined by parsing the `db` key to extract
        the dialect, and then looking that up under the `engines` key of the
        registry config.
        """
        dialect = self.getDialect()
        if dialect not in self["engines"]:
            raise ValueError(f"Connection string dialect has no known aliases. Received: {dialect}")
        databaseClassName = self["engines", dialect]
        databaseClass = doImportType(databaseClassName)
        if not issubclass(databaseClass, Database):
            raise TypeError(f"Imported database class {databaseClassName} is not a Database")
        return databaseClass

    def makeDefaultDatabaseUri(self, root: str) -> Optional[str]:
        """Return a default 'db' URI for the registry configured here that is
        appropriate for a new empty repository with the given root.

        Parameters
        ----------
        root : `str`
            Filesystem path to the root of the data repository.

        Returns
        -------
        uri : `str`
            URI usable as the 'db' string in a `RegistryConfig`.
        """
        DatabaseClass = self.getDatabaseClass()
        return DatabaseClass.makeDefaultUri(root)

    def replaceRoot(self, root: Optional[Union[str, ButlerURI]]) -> None:
        """Replace any occurrences of `BUTLER_ROOT_TAG` in the connection
        with the given root directory.

        Parameters
        ----------
        root : `str`, `ButlerURI`, or `None`
            String to substitute for `BUTLER_ROOT_TAG`.  Passing `None` here is
            allowed only as a convenient way to raise an exception
            (`ValueError`).

        Raises
        ------
        ValueError
            Raised if ``root`` is not set but a value is required.
        """
        self["db"] = replaceRoot(self["db"], root)

    @property
    def connectionString(self) -> sqlalchemy.engine.url.URL:
        """Return the connection string to the underlying database
        (`sqlalchemy.engine.url.URL`).
        """
        return ConnectionStringFactory.fromConfig(self)
