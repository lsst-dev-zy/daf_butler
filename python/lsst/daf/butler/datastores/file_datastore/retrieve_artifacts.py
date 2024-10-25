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

__all__ = ("determine_destination_for_retrieved_artifact", "retrieve_and_zip", "ZipIndex")

import logging
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Iterable
from typing import ClassVar, Self

from lsst.daf.butler import DatasetId, DatasetIdFactory, DatasetRef
from lsst.daf.butler.datastore.stored_file_info import SerializedStoredFileInfo, StoredFileInfo
from lsst.resources import ResourcePath, ResourcePathExpression
from pydantic import BaseModel

from ..._dataset_type import DatasetType, SerializedDatasetType
from ...dimensions import DataCoordinate, DimensionUniverse, SerializedDataCoordinate, SerializedDataId

_LOG = logging.getLogger(__name__)


class MinimalistDatasetRef(BaseModel):
    """Minimal information needed to define a DatasetRef.

    The ID is not included and is presumed to be the key to a mapping
    to this information.
    """

    dataset_type_name: str
    """Name of the dataset type."""

    run: str
    """Name of the RUN collection."""

    data_id: SerializedDataId
    """Data coordinate of this dataset."""


class SerializedDatasetRefContainer(BaseModel):
    """Serializable model for a collection of DatasetRef.

    Dimension records are not included.
    """

    universe_version: int
    """Dimension universe version."""

    universe_namespace: str
    """Dimension universe namespace."""

    dataset_types: dict[str, SerializedDatasetType]
    """Dataset types indexed by their name."""

    compact_refs: dict[uuid.UUID, MinimalistDatasetRef]
    """Minimal dataset ref information indexed by UUID."""

    def __len__(self) -> int:
        """Return the number of datasets in the container."""
        return len(self.compact_refs)

    @classmethod
    def from_refs(cls, refs: Iterable[DatasetRef]) -> Self:
        """Construct a serializable form from a list of `DatasetRef`.

        Parameters
        ----------
        refs : `~collections.abc.Iterable` [ `DatasetRef` ]
            The datasets to include in the container.
        """
        # The serialized DatasetRef contains a lot of duplicated information.
        # We also want to drop dimension records and assume that the records
        # are already in the registry.
        universe: DimensionUniverse | None = None
        dataset_types: dict[str, SerializedDatasetType] = {}
        compact_refs: dict[uuid.UUID, MinimalistDatasetRef] = {}
        for ref in refs:
            simple_ref = ref.to_simple()
            dataset_type = simple_ref.datasetType
            assert dataset_type is not None  # For mypy
            if universe is None:
                universe = ref.datasetType.dimensions.universe
            if (name := dataset_type.name) not in dataset_types:
                dataset_types[name] = dataset_type
            data_id = simple_ref.dataId
            assert data_id is not None  # For mypy
            compact_refs[simple_ref.id] = MinimalistDatasetRef(
                dataset_type_name=name, run=simple_ref.run, data_id=data_id.dataId
            )
        if universe:
            universe_version = universe.version
            universe_namespace = universe.namespace
        else:
            # No refs so no universe.
            universe_version = 0
            universe_namespace = "unknown"
        return cls(
            universe_version=universe_version,
            universe_namespace=universe_namespace,
            dataset_types=dataset_types,
            compact_refs=compact_refs,
        )

    def to_refs(self, universe: DimensionUniverse) -> list[DatasetRef]:
        """Construct the original `DatasetRef`.

        Parameters
        ----------
        universe : `DimensionUniverse`
            The universe to use when constructing the `DatasetRef`.

        Returns
        -------
        refs : `list` [ `DatasetRef` ]
            The `DatasetRef` that were serialized.
        """
        if not self.compact_refs:
            return []

        if universe.namespace != self.universe_namespace:
            raise RuntimeError(
                f"Can not convert to refs in universe {universe.namespace} that were created from "
                f"universe {self.universe_namespace}"
            )

        if universe.version != self.universe_version:
            _LOG.warning(
                "Universe mismatch when attempting to reconstruct DatasetRef from serialized form. "
                "Serialized with version %d but asked to use version %d.",
                self.universe_version,
                universe.version,
            )

        # Reconstruct the DatasetType objects.
        dataset_types = {
            name: DatasetType.from_simple(dtype, universe=universe)
            for name, dtype in self.dataset_types.items()
        }
        refs: list[DatasetRef] = []
        for id_, minimal in self.compact_refs.items():
            simple_data_id = SerializedDataCoordinate(dataId=minimal.data_id)
            data_id = DataCoordinate.from_simple(simple=simple_data_id, universe=universe)
            ref = DatasetRef(
                id=id_,
                run=minimal.run,
                datasetType=dataset_types[minimal.dataset_type_name],
                dataId=data_id,
            )
            refs.append(ref)
        return refs


class ZipIndex(BaseModel):
    """Index of a Zip file of Butler datasets.

    A file can be associated with multiple butler datasets and a single
    butler dataset can be associated with multiple files. This model
    provides the necessary information for ingesting back into a Butler
    file datastore.
    """

    refs: SerializedDatasetRefContainer
    """Deduplicated information for all the `DatasetRef` in the index."""

    ref_map: dict[str, list[uuid.UUID]]
    """Mapping of Zip member to one or more dataset UUIDs."""

    info_map: dict[str, SerializedStoredFileInfo]
    """Mapping of each Zip member to the associated datastore record."""

    index_name: ClassVar[str] = "_index.json"
    """Name to use when saving the index to a file."""

    def generate_uuid5(self) -> uuid.UUID:
        """Create a UUID based on the Zip index.

        Returns
        -------
        id_ : `uuid.UUID`
            A UUID5 created from the paths inside the Zip file. Guarantees
            that if the Zip file is regenerated with exactly the same file
            paths the same answer will be returned.
        """
        # Options are:
        # - uuid5 based on file paths in zip
        # - uuid5 based on ref uuids.
        # - checksum derived from the above.
        # - uuid5 from file paths and dataset refs.
        # Do not attempt to include file contents in UUID.
        # Start with uuid5 from file paths.
        data = ",".join(sorted(self.info_map.keys()))
        # No need to come up with a different namespace.
        return uuid.uuid5(DatasetIdFactory.NS_UUID, data)

    def __len__(self) -> int:
        """Return the number of files in the Zip."""
        return len(self.info_map)

    def calculate_zip_file_name(self) -> str:
        """Calculate the default name for the Zip file based on the index
        contents.

        Returns
        -------
        name : `str`
            Name of the zip file based on index.
        """
        return f"{self.generate_uuid5()}.zip"

    def write_index(self, dir: ResourcePath) -> ResourcePath:
        """Write the index to the specified directory.

        Parameters
        ----------
        dir : `~lsst.resources.ResourcePath`
            Directory to write the index file to.

        Returns
        -------
        index_path : `~lsst.resources.ResourcePath`
            Path to the index file that was written.
        """
        index_path = dir.join(self.index_name, forceDirectory=False)
        with index_path.open("w") as fd:
            print(self.model_dump_json(exclude_defaults=True, exclude_unset=True), file=fd)
        return index_path

    @classmethod
    def calc_relative_paths(
        cls, root: ResourcePath, paths: Iterable[ResourcePath]
    ) -> dict[ResourcePath, str]:
        """Calculate the path to use inside the Zip file from the full path.

        Parameters
        ----------
        root : `lsst.resources.ResourcePath`
            The reference root directory.
        paths : `~collections.abc.Iterable` [ `lsst.resources.ResourcePath` ]
            The paths to the files that should be included in the Zip file.

        Returns
        -------
        abs_to_rel : `dict` [ `~lsst.resources.ResourcePath`, `str` ]
            Mapping of the original file path to the relative path to use
            in Zip file.
        """
        file_to_relative: dict[ResourcePath, str] = {}
        for p in paths:
            # It is an error if there is no relative path.
            rel = p.relative_to(root)
            assert rel is not None
            file_to_relative[p] = rel
        return file_to_relative

    @classmethod
    def from_artifact_maps(
        cls,
        refs: Iterable[DatasetRef],
        id_map: dict[ResourcePath, list[DatasetId]],
        info_map: dict[ResourcePath, StoredFileInfo],
        root: ResourcePath,
    ) -> Self:
        """Create an index from the mappings returned from
        `Datastore.retrieveArtifacts`.

        Parameters
        ----------
        refs : `~collections.abc.Iterable` [ `DatasetRef` ]
            Datasets present in the index.
        id_map : `dict` [ `lsst.resources.ResourcePath`, \
                `list` [ `uuid.UUID`] ]
            Mapping of retrieved artifact path to `DatasetRef` ID.
        info_map : `dict` [ `~lsst.resources.ResourcePath`, \
                `StoredDatastoreItemInfo` ]
            Mapping of retrieved artifact path to datastore record information.
        root : `lsst.resources.ResourcePath`
            Root path to be removed from all the paths before creating the
            index.
        """
        if not refs:
            return cls(
                universe_version=0,
                universe_namespace="daf_butler",
                refs=SerializedDatasetRefContainer.from_refs(refs),
                ref_map={},
                info_map={},
            )

        # Calculate the paths relative to the given root since the Zip file
        # uses relative paths.
        file_to_relative = cls.calc_relative_paths(root, info_map.keys())

        simplified_refs = SerializedDatasetRefContainer.from_refs(refs)

        # Convert the mappings to simplified form for pydantic.
        # and use the relative paths that will match the zip.
        simplified_ref_map = {}
        for path, ids in id_map.items():
            simplified_ref_map[file_to_relative[path]] = ids
        simplified_info_map = {file_to_relative[path]: info.to_simple() for path, info in info_map.items()}

        return cls(
            refs=simplified_refs,
            ref_map=simplified_ref_map,
            info_map=simplified_info_map,
        )

    @classmethod
    def from_zip_file(cls, zip_path: ResourcePath) -> Self:
        """Given a path to a Zip file return the index.

        Parameters
        ----------
        zip_path : `lsst.resources.ResourcePath`
            Path to the Zip file.
        """
        with zip_path.open("rb") as fd, zipfile.ZipFile(fd) as zf:
            json_data = zf.read(cls.index_name)
        return cls.model_validate_json(json_data)


def determine_destination_for_retrieved_artifact(
    destination_directory: ResourcePath, source_path: ResourcePath, preserve_path: bool, prefix: str = ""
) -> ResourcePath:
    """Determine destination path for an artifact retrieved from a datastore.

    Parameters
    ----------
    destination_directory : `ResourcePath`
        Path to the output directory where file will be stored.
    source_path : `ResourcePath`
        Path to the source file to be transferred.  This may be relative to the
        datastore root, or an absolute path.
    preserve_path : `bool`
        If `True` the full path of the artifact within the datastore
        is preserved. If `False` the final file component of the path
        is used.
    prefix : `str`, optional
        Prefix to add to the file name if ``preserve_path`` is `False`.

    Returns
    -------
    destination_uri : `~lsst.resources.ResourcePath`
        Absolute path to the output destination.
    """
    destination_directory = destination_directory.abspath()

    target_path: ResourcePathExpression
    if preserve_path:
        target_path = source_path
        if target_path.isabs():
            # This is an absolute path to an external file.
            # Use the full path.
            target_path = target_path.relativeToPathRoot
    else:
        target_path = source_path.basename()
        if prefix:
            target_path = prefix + target_path

    target_uri = destination_directory.join(target_path).abspath()
    if target_uri.relative_to(destination_directory) is None:
        raise ValueError(f"File path attempts to escape destination directory: '{source_path}'")
    return target_uri


def retrieve_and_zip(
    refs: Iterable[DatasetRef],
    destination: ResourcePathExpression,
    retrieval_callback: Callable[
        [Iterable[DatasetRef], ResourcePath, str, bool, bool, bool, bool],
        tuple[list[ResourcePath], dict[ResourcePath, list[DatasetId]], dict[ResourcePath, StoredFileInfo]],
    ],
) -> ResourcePath:
    """Retrieve artifacts from a Butler and place in ZIP file.

    Parameters
    ----------
    refs : `collections.abc.Iterable` [ `DatasetRef` ]
        The datasets to be included in the zip file. Must all be from
        the same dataset type.
    destination : `lsst.resources.ResourcePath`
        Directory to write the new ZIP file. This directory will
        also be used as a staging area for the datasets being downloaded
        from the datastore.
    retrieval_callback : `~collections.abc.Callable`
        Bound method for a function that can retrieve the artifacts and
        return the metadata necessary for creating the zip index. For example
        `lsst.daf.butler.datastore.Datastore.retrieveArtifacts`.

    Returns
    -------
    zip_file : `lsst.resources.ResourcePath`
        The path to the new ZIP file.
    """
    outdir = ResourcePath(destination, forceDirectory=True)
    if not outdir.isdir():
        raise ValueError(f"Destination location must refer to a directory. Given {destination}")

    if not outdir.exists():
        outdir.mkdir()

    # Simplest approach:
    # - create temp dir in destination
    # - Run retrieveArtifacts to that temp dir
    # - Create zip file with unique name.
    # - Delete temp dir
    # - Add index file to ZIP.
    # - Return name of zip file.
    with tempfile.TemporaryDirectory(dir=outdir.ospath, ignore_cleanup_errors=True) as tmpdir:
        tmpdir_path = ResourcePath(tmpdir, forceDirectory=True)
        # Retrieve the artifacts and write the index file. Strip paths.
        paths, _, _ = retrieval_callback(refs, tmpdir_path, "auto", False, False, True, True)

        # Read the index to construct file name.
        index_path = tmpdir_path.join(ZipIndex.index_name, forceDirectory=False)
        index_json = index_path.read()
        index = ZipIndex.model_validate_json(index_json)

        # Use unique name based on files in Zip.
        zip_file_name = index.calculate_zip_file_name()
        zip_path = outdir.join(zip_file_name, forceDirectory=False)
        with zipfile.ZipFile(zip_path.ospath, "w") as zip:
            zip.write(index_path.ospath, index_path.basename())
            for path, name in index.calc_relative_paths(tmpdir_path, paths).items():
                zip.write(path.ospath, name)

    return zip_path
