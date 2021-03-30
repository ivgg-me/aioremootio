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

import unittest
import aioremootio
import tests
import asyncio
import aiohttp


class RemootioDeviceTestCase(unittest.TestCase):
    remootio_device_configuration: tests.RemootioDeviceConfiguration

    def setUp(self) -> None:
        super().setUp()
        self.remootio_device_configuration = tests.create_remootio_device_configurations()

    def test_remootio_device(self):
        asyncio.get_event_loop().run_until_complete(self.__test_remootio_device())

    async def __test_remootio_device(self):
        async with aiohttp.ClientSession() as client_session:
            device: aioremootio.Device = \
                await aioremootio.Device(self.remootio_device_configuration, client_session)

            self.assertEqual(device.api_version, self.remootio_device_configuration.api_version)


if __name__ == '__main__':
    unittest.main()
