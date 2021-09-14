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

__all__ = ("VERBOSE", "ButlerMDC", "ButlerLogRecords", "ButlerLogRecordHandler",
           "ButlerLogRecord", "JsonLogFormatter")

import logging
import datetime
import traceback
from contextlib import contextmanager
from typing import List, Union, Optional, ClassVar, Iterable, Iterator, Dict, IO, Any, Generator

from logging import LogRecord, StreamHandler, Formatter
from pydantic import BaseModel, PrivateAttr

from .utils import isplit

VERBOSE = (logging.INFO + logging.DEBUG) // 2
"""Verbose log level"""

_LONG_LOG_FORMAT = "{levelname} {asctime} {name} {filename}:{lineno} - {message}"
"""Default format for log records."""

logging.addLevelName(VERBOSE, "VERBOSE")


class MDCDict(dict):
    """Dictionary for MDC data.

    This is internal class used for better formatting of MDC in Python logging
    output. It behaves like `defaultdict(str)` but overrides ``__str__`` and
    ``__repr__`` method to produce output better suited for logging records.
    """

    def __getitem__(self, name: str) -> str:
        """Return value for a given key or empty string for missing key.
        """
        return self.get(name, "")

    def __str__(self) -> str:
        """Return string representation, strings are interpolated without
        quotes.
        """
        items = (f"{k}={self[k]}" for k in sorted(self))
        return "{" + ", ".join(items) + "}"

    def __repr__(self) -> str:
        return str(self)


class ButlerMDC:
    """Handle setting and unsetting of global MDC records.

    The Mapped Diagnostic Context (MDC) can be used to set context
    for log messages.

    Currently there is one global MDC dict. Per-thread MDC is not
    yet supported.
    """

    _MDC = MDCDict()

    _old_factory = None
    """Old log record factory."""

    @classmethod
    def MDC(cls, key: str, value: str) -> str:
        """Set MDC for this key to the supplied value.

        Parameters
        ----------
        key : `str`
            Key to modify.
        value : `str`
            New value to use.

        Returns
        -------
        old : `str`
            The previous value for this key.
        """
        old_value = cls._MDC[key]
        cls._MDC[key] = value
        return old_value

    @classmethod
    def MDCRemove(cls, key: str) -> None:
        """Clear the MDC value associated with this key.

        Can be called even if the key is not known to MDC.
        """
        cls._MDC.pop(key, None)

    @classmethod
    @contextmanager
    def set_mdc(cls, mdc: Dict[str, str]) -> Generator[None, None, None]:
        """Set the MDC key for this context.

        Parameters
        ----------
        mdc : `dict` of `str`, `str`
            MDC keys to update temporarily.

        Notes
        -----
        Other MDC keys are not modified. The previous values are restored
        on exit (removing them if the were unset previously).
        """
        previous = {}
        for k, v in mdc.items():
            previous[k] = cls.MDC(k, v)

        try:
            yield
        finally:
            for k, v in previous.items():
                if not v:
                    cls.MDCRemove(k)
                else:
                    cls.MDC(k, v)

    @classmethod
    def add_mdc_log_record_factory(cls) -> None:
        """Add a log record factory that adds a MDC record to `LogRecord`.
        """
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args: Any, **kwargs: Any) -> LogRecord:
            record = old_factory(*args, **kwargs)
            # Make sure we send a copy of the global dict in the record.
            record.MDC = MDCDict(cls._MDC)  # type: ignore
            return record

        cls._old_factory = old_factory
        logging.setLogRecordFactory(record_factory)

    @classmethod
    def restore_log_record_factory(cls) -> None:
        """Restores the log record factory to the original form.

        Does nothing if there has not been a call to
        `add_mdc_log_record_factory`.
        """
        if cls._old_factory:
            logging.setLogRecordFactory(cls._old_factory)


class ButlerLogRecord(BaseModel):
    """A model representing a `logging.LogRecord`.

    A `~logging.LogRecord` always uses the current time in its record
    when recreated and that makes it impossible to use it as a
    serialization format. Instead have a local representation of a
    `~logging.LogRecord` that matches Butler needs.
    """

    _log_format: ClassVar[str] = _LONG_LOG_FORMAT

    name: str
    asctime: datetime.datetime
    message: str
    levelno: int
    levelname: str
    filename: str
    pathname: str
    lineno: int
    funcName: Optional[str]
    process: int
    processName: str
    exc_info: Optional[str]
    MDC: Dict[str, str]

    class Config:
        """Pydantic model configuration."""

        allow_mutation = False

    @classmethod
    def from_record(cls, record: LogRecord) -> ButlerLogRecord:
        """Create a new instance from a `~logging.LogRecord`.

        Parameters
        ----------
        record : `logging.LogRecord`
            The record from which to extract the relevant information.
        """
        # The properties that are one-to-one mapping.
        simple = ("name", "levelno", "levelname", "filename", "pathname",
                  "lineno", "funcName", "process", "processName")

        record_dict = {k: getattr(record, k) for k in simple}

        record_dict["message"] = record.getMessage()

        # MDC -- ensure the contents are copied to prevent any confusion
        # over the MDC global being updated later.
        record_dict["MDC"] = dict(getattr(record, "MDC", {}))

        # Always use UTC because in distributed systems we can't be sure
        # what timezone localtime is and it's easier to compare logs if
        # every system is using the same time.
        record_dict["asctime"] = datetime.datetime.fromtimestamp(record.created,
                                                                 tz=datetime.timezone.utc)

        # Sometimes exception information is included so must be
        # extracted.
        if record.exc_info:
            etype = record.exc_info[0]
            evalue = record.exc_info[1]
            tb = record.exc_info[2]
            record_dict["exc_info"] = "\n".join(traceback.format_exception(etype, evalue, tb))

        return cls(**record_dict)

    def format(self, log_format: Optional[str] = None) -> str:
        """Format this record.

        Parameters
        ----------
        log_format : `str`, optional
            The format string to use. This string follows the standard
            f-style use for formatting log messages. If `None`
            the class default will be used.

        Returns
        -------
        text : `str`
            The formatted log message.
        """
        if log_format is None:
            log_format = self._log_format

        as_dict = self.dict()

        # Special case MDC content. Convert it to an MDCDict
        # so that missing items do not break formatting.
        as_dict["MDC"] = MDCDict(as_dict["MDC"])

        as_dict["asctime"] = as_dict["asctime"].isoformat()
        formatted = log_format.format(**as_dict)
        return formatted

    def __str__(self) -> str:
        return self.format()


# The class below can convert LogRecord to ButlerLogRecord if needed.
Record = Union[LogRecord, ButlerLogRecord]


# Do not inherit from MutableSequence since mypy insists on the values
# being Any even though we wish to constrain them to Record.
class ButlerLogRecords(BaseModel):
    """Class representing a collection of `ButlerLogRecord`.
    """

    __root__: List[ButlerLogRecord]
    _log_format: Optional[str] = PrivateAttr(None)

    @classmethod
    def from_records(cls, records: Iterable[ButlerLogRecord]) -> ButlerLogRecords:
        """Create collection from iterable.

        Parameters
        ----------
        records : iterable of `ButlerLogRecord`
            The records to seed this class with.
        """
        return cls(__root__=list(records))

    @classmethod
    def from_file(cls, filename: str) -> ButlerLogRecords:
        """Read records from file.

        Parameters
        ----------
        filename : `str`
            Name of file containing the JSON records.

        Notes
        -----
        Works with one-record-per-line format JSON files and a direct
        serialization of the Pydantic model.
        """
        with open(filename, "r") as fd:
            return cls.from_stream(fd)

    @staticmethod
    def _detect_model(startdata: Union[str, bytes]) -> bool:
        """Given some representative data, determine if this is a serialized
        model or a streaming format.

        Parameters
        ----------
        startdata : `bytes` or `str`
            Representative characters or bytes from the start of a serialized
            collection of log records.

        Returns
        -------
        is_model : `bool`
            Returns `True` if the data look like a serialized pydantic model.
            Returns `False` if it looks like a streaming format. Returns
            `False` also if an empty string is encountered since this
            is not understood by `ButlerLogRecords.parse_raw()`.

        Raises
        ------
        ValueError
            Raised if the sentinel doesn't look like either of the supported
            log record formats.
        """
        if not startdata:
            return False

        # Allow byte or str streams since pydantic supports either.
        # We don't want to convert the entire input to unicode unnecessarily.
        error_type = "str"
        if isinstance(startdata, bytes):
            first_char = chr(startdata[0])
            error_type = "byte"
        else:
            first_char = startdata[0]

        if first_char == "[":
            # This is an array of records.
            return True
        if first_char != "{":
            # Limit the length of string reported in error message in case
            # this is an enormous file.
            max = 32
            if len(startdata) > max:
                startdata = f"{startdata[:max]!r}..."
            raise ValueError("Unrecognized JSON log format. Expected '{' or '[' but got"
                             f" {first_char!r} from {error_type} content starting with {startdata!r}")

        # Assume a record per line.
        return False

    @classmethod
    def from_stream(cls, stream: IO) -> ButlerLogRecords:
        """Read records from I/O stream.

        Parameters
        ----------
        stream : `typing.IO`
            Stream from which to read JSON records.

        Notes
        -----
        Works with one-record-per-line format JSON files and a direct
        serialization of the Pydantic model.
        """
        first_line = stream.readline()

        if not first_line:
            # Empty file, return zero records.
            return cls.from_records([])

        is_model = cls._detect_model(first_line)

        if is_model:
            # This is a ButlerLogRecords model serialization so all the
            # content must be read first.
            all = first_line + stream.read()
            return cls.parse_raw(all)

        # A stream of records with one record per line.
        records = [ButlerLogRecord.parse_raw(first_line)]
        for line in stream:
            line = line.rstrip()
            if line:  # Filter out blank lines.
                records.append(ButlerLogRecord.parse_raw(line))

        return cls.from_records(records)

    @classmethod
    def from_raw(cls, serialized: Union[str, bytes]) -> ButlerLogRecords:
        """Parse raw serialized form and return records.

        Parameters
        ----------
        serialized : `bytes` or `str`
            Either the serialized JSON of the model created using
            ``.json()`` or a streaming format of one JSON `ButlerLogRecord`
            per line. This can also support a zero-length string.
        """
        if not serialized:
            # No records to return
            return cls.from_records([])

        # Only send the first character for analysis.
        is_model = cls._detect_model(serialized)

        if is_model:
            return cls.parse_raw(serialized)

        # Filter out blank lines -- mypy is confused by the newline
        # argument to split().
        newline = "\n" if isinstance(serialized, str) else b"\n"
        records = [ButlerLogRecord.parse_raw(line) for line in isplit(serialized, newline)  # type: ignore
                   if line]
        return cls.from_records(records)

    @property
    def log_format(self) -> str:
        if self._log_format is None:
            return _LONG_LOG_FORMAT
        return self._log_format

    # Pydantic does not allow a property setter to be given for
    # public properties of a model that is not based on a dict.
    def set_log_format(self, format: Optional[str]) -> Optional[str]:
        """Set the log format string for these records.

        Parameters
        ----------
        format : `str`, optional
            The new format string to use for converting this collection
            of records into a string. If `None` the default format will be
            used.

        Returns
        -------
        old_format : `str`, optional
            The previous log format.
        """
        previous = self._log_format
        self._log_format = format
        return previous

    def __len__(self) -> int:
        return len(self.__root__)

    # The signature does not match the one in BaseModel but that is okay
    # if __root__ is being used.
    # See https://pydantic-docs.helpmanual.io/usage/models/#custom-root-types
    def __iter__(self) -> Iterator[ButlerLogRecord]:  # type: ignore
        return iter(self.__root__)

    def __setitem__(self, index: int, value: Record) -> None:
        self.__root__[index] = self._validate_record(value)

    def __getitem__(self, index: Union[slice, int]) -> Union[ButlerLogRecords, ButlerLogRecord]:
        # Handles slices and returns a new collection in that
        # case.
        item = self.__root__[index]
        if isinstance(item, list):
            return type(self)(__root__=item)
        else:
            return item

    def __reversed__(self) -> Iterator[ButlerLogRecord]:
        return self.__root__.__reversed__()

    def __delitem__(self, index: Union[slice, int]) -> None:
        del self.__root__[index]

    def __str__(self) -> str:
        # Ensure that every record uses the same format string.
        return "\n".join(record.format(self.log_format) for record in self.__root__)

    def _validate_record(self, record: Record) -> ButlerLogRecord:
        if isinstance(record, ButlerLogRecord):
            pass
        elif isinstance(record, LogRecord):
            record = ButlerLogRecord.from_record(record)
        else:
            raise ValueError(f"Can only append item of type {type(record)}")
        return record

    def insert(self, index: int, value: Record) -> None:
        self.__root__.insert(index, self._validate_record(value))

    def append(self, value: Record) -> None:
        value = self._validate_record(value)
        self.__root__.append(value)

    def clear(self) -> None:
        self.__root__.clear()

    def extend(self, records: Iterable[Record]) -> None:
        self.__root__.extend(self._validate_record(record) for record in records)

    def pop(self, index: int = -1) -> ButlerLogRecord:
        return self.__root__.pop(index)

    def reverse(self) -> None:
        self.__root__.reverse()


class ButlerLogRecordHandler(StreamHandler):
    """Python log handler that accumulates records.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records = ButlerLogRecords(__root__=[])

    def emit(self, record: LogRecord) -> None:
        self.records.append(record)


class JsonLogFormatter(Formatter):
    """Format a `LogRecord` in JSON format."""

    def format(self, record: LogRecord) -> str:
        butler_record = ButlerLogRecord.from_record(record)
        return butler_record.json(exclude_unset=True, exclude_defaults=True)