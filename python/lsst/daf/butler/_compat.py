# This file is part of pipe_base.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Code to support backwards compatibility."""

__all__ = ["PYDANTIC_V2", "_BaseModelCompat"]

from collections.abc import Callable, Mapping
from typing import Any, Self

from pydantic import BaseModel
from pydantic.version import VERSION as PYDANTIC_VERSION

PYDANTIC_V2 = PYDANTIC_VERSION.startswith("2.")


if PYDANTIC_V2:

    class _BaseModelCompat(BaseModel):
        """Methods from pydantic v1 that we want to emulate in v2.

        Some of these methods are provided by v2 but issue deprecation
        warnings.  We need to decide whether we are also okay with deprecating
        them or want to support them without the deprecation message.
        """

        def json(
            self,
            *,
            include: set[int | str] | Mapping[int | str, Any] | None = None,
            exclude: set[int | str] | Mapping[int | str, Any] | None = None,
            by_alias: bool = False,
            skip_defaults: bool | None = None,
            exclude_unset: bool = False,
            exclude_defaults: bool = False,
            exclude_none: bool = False,
            encoder: Callable[[Any], Any] | None = None,
            models_as_dict: bool = True,
            **dumps_kwargs: Any,
        ) -> str:
            if dumps_kwargs:
                raise TypeError("dumps_kwargs no longer supported.")
            if encoder is not None:
                raise TypeError("json encoder is no longer supported.")
            # Can catch warnings and call BaseModel.json() directly.
            return self.model_dump_json(
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                exclude_unset=exclude_unset,
            )

        @classmethod
        def parse_obj(cls, obj: Any) -> Self:
            # Catch warnings and call BaseModel.parse_obj directly?
            return cls.model_validate(obj)

else:

    class _BaseModelCompat(BaseModel):
        @classmethod
        def model_validate(
            cls,
            obj: Any,
            *,
            strict: bool | None = None,
            from_attributes: bool | None = None,
            context: dict[str, Any] | None = None,
        ) -> Self:
            return cls.parse_obj(obj)

        def model_dump_json(
            self,
            *,
            indent: int | None = None,
            include: set[int] | set[str] | dict[int, Any] | dict[str, Any] | None = None,
            exclude: set[int] | set[str] | dict[int, Any] | dict[str, Any] | None = None,
            by_alias: bool = False,
            exclude_unset: bool = False,
            exclude_defaults: bool = False,
            exclude_none: bool = False,
            round_trip: bool = False,
            warnings: bool = True,
        ) -> str:
            return self.json(
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            )
