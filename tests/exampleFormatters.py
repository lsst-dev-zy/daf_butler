#
# LSST Data Management System
#
# Copyright 2018  AURA/LSST.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
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
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <https://www.lsstcorp.org/LegalNotices/>.
#

from lsst.daf.butler.core.formatter import Formatter
import json


class MetricsExampleFormatter(Formatter):
    """Interface for reading and writing example metrics to and from JSON files.
    """

    def read(self, fileDescriptor):
        """Read a `MetricsExample` from a JSON file.

        Parameters
        ----------
        fileDescriptor : `FileDescriptor`
            Identifies the file to read, type to read it into and parameters
            to be used for reading.

        Returns
        -------
        inMemoryDataset : `MetricsExample`
            The requested `MetricsExample`.
        """
        with open(fileDescriptor.location.path, "r") as fd:
            data = json.load(fd)
        return fileDescriptor.pytype.makeFromDict(data)

    def write(self, inMemoryDataset, fileDescriptor):
        """Write a `MetricsExample` to a JSON file.

        Parameters
        ----------
        inMemoryDataset : `MetricsExample`
            The `MetricsExample` to store.
        fileDescriptor : `FileDescriptor`
            Identifies the file to read, type to read it into and parameters
            to be used for reading.

        Returns
        -------
        uri : `str`
            The `URI` where the primary `MetricsExample` is stored.
        components : `dict`, optional
            A dictionary of URIs for the `MetricsExample`' components.
            The latter will be empty if the `MetricsExample` is not a composite.
        """
        data = inMemoryDataset.exportAsDict()
        print("Input: {}".format(inMemoryDataset))
        print("Writing {}".format(data))
        print("Output location: {}".format(fileDescriptor.location.path))
        with open(fileDescriptor.location.path, "w") as fd:
            json.dump(data, fd)
        print("URI: {}".format(fileDescriptor.location.uri))
        return fileDescriptor.location.uri, {}
