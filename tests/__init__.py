# Copyright 2021 Gergö Gabor Ilyes-Veisz
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass
from typing import Union
from aioremootio.models import ConnectionOptions
import json
import os
import sys


@dataclass(frozen=True)
class RemootioDeviceConfiguration(ConnectionOptions):
    api_version: int


def create_remootio_device_configurations(
        default_device_configuration: Union[RemootioDeviceConfiguration, dict] = None
) -> RemootioDeviceConfiguration:
    result = None

    filename = "remootio_devices.configuration.json"

    if os.path.isfile(filename):
        try:
            with open(filename, "r") as af:
                result = RemootioDeviceConfiguration(**json.load(af))
        except:
            print("Can't read file. File [%s] Cause [%s]" % (
                filename,
                ': '.join(str(exc_info_item) for exc_info_item in sys.exc_info()[:2])
            ))
    elif type(default_device_configuration) is dict:
        result = RemootioDeviceConfiguration(**default_device_configuration)
    else:
        result = default_device_configuration

    return result
