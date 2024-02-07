import dataclasses
from dataclasses import dataclass
from typing import List
from enum import Enum

import dataconf


class ConfigurationBase:

    @staticmethod
    def fromDict(parameters: dict):
        return dataconf.dict(parameters, Configuration, ignore_unexpected=True)
        pass

    @staticmethod
    def _convert_private_value_inv(value: str):
        if value and value.startswith('pswd_'):
            return value.replace('pswd_', '#', 1)
        else:
            return value

    @classmethod
    def get_dataclass_required_parameters(cls) -> List[str]:
        """
        Return list of required parameters based on the dataclass definition (no default value)
        Returns: List[str]

        """
        return [cls._convert_private_value_inv(f.name) for f in dataclasses.fields(cls)
                if f.default == dataclasses.MISSING
                and f.default_factory == dataclasses.MISSING]


class Operation(str, Enum):
    delete = "delete"
    create_and_update = "create_and_update"
    upsert = "upsert"


@dataclass
class Configuration(ConfigurationBase):
    api_version: str
    organization_url: str
    operation: Operation
    continue_on_error: bool = True
    debug: bool = False
