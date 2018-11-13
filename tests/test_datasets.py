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

import unittest
import pickle

import lsst.utils.tests

from lsst.daf.butler.core.datasets import DatasetType, DatasetRef
from lsst.daf.butler.core.storageClass import StorageClass, StorageClassFactory

"""Tests for datasets module.
"""


class DatasetTypeTestCase(lsst.utils.tests.TestCase):
    """Test for DatasetType.
    """

    def testConstructor(self):
        """Test construction preserves values.

        Note that construction doesn't check for valid storageClass or
        dataUnits parameters.
        These can only be verified for a particular schema.
        """
        datasetTypeName = "test"
        storageClass = StorageClass("test_StructuredData")
        dataUnits = frozenset(("instrument", "visit"))
        datasetType = DatasetType(datasetTypeName, dataUnits, storageClass)
        self.assertEqual(datasetType.name, datasetTypeName)
        self.assertEqual(datasetType.storageClass, storageClass)
        self.assertEqual(datasetType.dataUnits, dataUnits)

    def testConstructor2(self):
        """Test construction from StorageClass name.
        """
        datasetTypeName = "test"
        storageClass = StorageClass("test_constructor2")
        StorageClassFactory().registerStorageClass(storageClass)
        dataUnits = frozenset(("instrument", "visit"))
        datasetType = DatasetType(datasetTypeName, dataUnits, "test_constructor2")
        self.assertEqual(datasetType.name, datasetTypeName)
        self.assertEqual(datasetType.storageClass, storageClass)
        self.assertEqual(datasetType.dataUnits, dataUnits)

    def testEquality(self):
        storageA = StorageClass("test_a")
        storageB = StorageClass("test_b")
        self.assertEqual(DatasetType("a", ("UnitA", ), storageA,),
                         DatasetType("a", ("UnitA", ), storageA,))
        self.assertEqual(DatasetType("a", ("UnitA", ), "test_a",),
                         DatasetType("a", ("UnitA", ), storageA,))
        self.assertEqual(DatasetType("a", ("UnitA", ), storageA,),
                         DatasetType("a", ("UnitA", ), "test_a",))
        self.assertEqual(DatasetType("a", ("UnitA", ), "test_a",),
                         DatasetType("a", ("UnitA", ), "test_a",))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("b", ("UnitA", ), storageA,))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("b", ("UnitA", ), "test_a",))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("a", ("UnitA", ), storageB,))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("a", ("UnitA", ), "test_b",))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("a", ("UnitB", ), storageA,))
        self.assertNotEqual(DatasetType("a", ("UnitA", ), storageA,),
                            DatasetType("a", ("UnitB", ), "test_a",))

    def testHashability(self):
        """Test `DatasetType.__hash__`.

        This test is performed by checking that `DatasetType` entries can
        be inserted into a `set` and that unique values of its
        (`name`, `storageClass`, `dataUnits`) parameters result in separate
        entries (and equal ones don't).

        This does not check for uniformity of hashing or the actual values
        of the hash function.
        """
        types = []
        unique = 0
        storageC = StorageClass("test_c")
        storageD = StorageClass("test_d")
        for name in ["a", "b"]:
            for storageClass in [storageC, storageD]:
                for dataUnits in [("e", ), ("f", )]:
                    datasetType = DatasetType(name, dataUnits, storageClass)
                    datasetTypeCopy = DatasetType(name, dataUnits, storageClass)
                    types.extend((datasetType, datasetTypeCopy))
                    unique += 1  # datasetType should always equal its copy
        self.assertEqual(len(set(types)), unique)  # all other combinations are unique

        # also check that hashes of instances constructed with StorageClass
        # name matches hashes of instances constructed with instances
        self.assertEqual(hash(DatasetType("a", ("e",), storageC)),
                         hash(DatasetType("a", ("e",), "test_c")))
        self.assertEqual(hash(DatasetType("a", ("e",), "test_c")),
                         hash(DatasetType("a", ("e",), "test_c")))
        self.assertNotEqual(hash(DatasetType("a", ("e",), storageC)),
                            hash(DatasetType("a", ("e",), "test_d")))
        self.assertNotEqual(hash(DatasetType("a", ("e",), storageD)),
                            hash(DatasetType("a", ("e",), "test_c")))
        self.assertNotEqual(hash(DatasetType("a", ("e",), "test_c")),
                            hash(DatasetType("a", ("e",), "test_d")))

    def testPickle(self):
        """Test pickle support.
        """
        storageClass = StorageClass("test_pickle")
        datasetTypeName = "test"
        dataUnits = frozenset(("camera", "visit"))
        # Un-pickling requires that storage class is registered with factory.
        StorageClassFactory().registerStorageClass(storageClass)
        datasetType = DatasetType(datasetTypeName, dataUnits, storageClass)
        datasetTypeOut = pickle.loads(pickle.dumps(datasetType))
        self.assertIsInstance(datasetTypeOut, DatasetType)
        self.assertEqual(datasetType.name, datasetTypeOut.name)
        self.assertEqual(datasetType.dataUnits, datasetTypeOut.dataUnits)
        self.assertEqual(datasetType.storageClass, datasetTypeOut.storageClass)


class DatasetRefTestCase(lsst.utils.tests.TestCase):
    """Test for DatasetRef.
    """
    def testConstructor(self):
        """Test construction preserves values.
        """
        datasetTypeName = "test"
        storageClass = StorageClass("testref_StructuredData")
        dataUnits = frozenset(("instrument", "visit"))
        dataId = dict(instrument="DummyCam", visit=42)
        datasetType = DatasetType(datasetTypeName, dataUnits, storageClass)
        ref = DatasetRef(datasetType, dataId)
        self.assertEqual(ref.datasetType, datasetType)
        self.assertEqual(ref.dataId, dataId)
        self.assertIsNone(ref.producer)
        self.assertEqual(ref.predictedConsumers, dict())
        self.assertEqual(ref.actualConsumers, dict())
        self.assertEqual(ref.components, dict())

    def testDetach(self):
        datasetTypeName = "test"
        storageClass = StorageClass("testref_StructuredData")
        dataUnits = frozenset(("instrument", "visit"))
        dataId = dict(instrument="DummyCam", visit=42)
        datasetType = DatasetType(datasetTypeName, dataUnits, storageClass)
        ref = DatasetRef(datasetType, dataId, id=1)
        detachedRef = ref.detach()
        self.assertIsNotNone(ref.id)
        self.assertIsNone(detachedRef.id)
        self.assertEqual(ref.datasetType, detachedRef.datasetType)
        self.assertEqual(ref.dataId, detachedRef.dataId)
        self.assertEqual(ref.predictedConsumers, detachedRef.predictedConsumers)
        self.assertEqual(ref.actualConsumers, detachedRef.actualConsumers)
        self.assertEqual(ref.components, detachedRef.components)


class MemoryTester(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    lsst.utils.tests.init()
    unittest.main()
