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

from typing import Optional, NoReturn, Callable, Awaitable

from aioremootio.listeners import T
from aioremootio.models import LoggerConfiguration
from aioremootio.enums import State
import unittest
import aioremootio
import logging
import tests
import asyncio
import aiohttp


class RemootioClientTestStateChangeListener(aioremootio.Listener[aioremootio.StateChange]):

    __invoke_count: int

    def __init__(self):
        self.__invoke_count = 0

    async def execute(self, client: aioremootio.RemootioClient, subject: aioremootio.StateChange) -> NoReturn:
        self.__invoke_count = self.__invoke_count + 1

    @property
    def invoke_count(self) -> int:
        return self.__invoke_count


class RemootioClientTestCase(unittest.TestCase):
    TIMEOUT = 200
    DEFAULT_MAXIMUM_ATTEMPTS = 200
    WAIT_TIME_BETWEEN_ATTEMPTS = 1

    __logger: Optional[logging.Logger]
    __remootio_device_configuration: Optional[tests.RemootioDeviceConfiguration]
    __state_change_listener: RemootioClientTestStateChangeListener

    def setUp(self) -> NoReturn:
        super().setUp()

        self.__logger = logging.getLogger(__name__)
        self.__logger.setLevel(logging.DEBUG)

        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
        self.__logger.addHandler(handler)

        self.__remootio_device_configuration = tests.create_remootio_device_configurations()
        self.__state_change_listener = RemootioClientTestStateChangeListener()

    def test_remootio_device(self):
        if self.__remootio_device_configuration is not None:
            asyncio.get_event_loop().run_until_complete(self.__test_remootio_device())
        else:
            logging.info("Tests will be skipped because of missing Remootio device configuration.")

    async def __test_remootio_device(self):
        async with aiohttp.ClientSession() as client_session:
            remootio_client: aioremootio.RemootioClient = \
                await aioremootio.RemootioClient(
                    self.__remootio_device_configuration,
                    client_session,
                    LoggerConfiguration(logger=self.__logger),
                    self.__state_change_listener
                )

            await asyncio.wait_for(
                self.__condition_is_met(self.__is_api_version_not_none, remootio_client),
                timeout=RemootioClientTestCase.TIMEOUT
            )

            self.assertEqual(remootio_client.api_version, self.__remootio_device_configuration.api_version,
                             "API version isn't the expected.")

            if remootio_client.api_version >= 2:
                await asyncio.wait_for(
                    self.__condition_is_met(self.__is_serial_number_not_none, remootio_client),
                    timeout=RemootioClientTestCase.TIMEOUT
                )

                self.assertIsNotNone(
                    remootio_client.serial_number,
                    "By devices with API version >= 2 serial number must be set after successful initialization of "
                    "the client.")

            await asyncio.wait_for(
                self.__condition_is_met(self.__is_state_change_listener_invoked, remootio_client,
                                        expected_invoke_count=2),
                timeout=RemootioClientTestCase.TIMEOUT
            )

            self.assertNotEqual(remootio_client.state, State.UNKNOWN, "State isn't the expected.")

            if remootio_client.state != State.NO_SENSOR_INSTALLED:
                if remootio_client.state == State.OPEN:
                    await remootio_client.trigger_close()

                    await asyncio.wait_for(
                        self.__condition_is_met(self.__is_state_change_listener_invoked, remootio_client,
                                                expected_invoke_count=4),
                        timeout=RemootioClientTestCase.TIMEOUT
                    )

                    self.assertEqual(remootio_client.state, State.CLOSED, "State isn't the expected.")

                    await remootio_client.trigger_open()

                    await asyncio.wait_for(
                        self.__condition_is_met(self.__is_state_change_listener_invoked, remootio_client,
                                                expected_invoke_count=6),
                        timeout=RemootioClientTestCase.TIMEOUT
                    )

                    self.assertEqual(remootio_client.state, State.OPEN, "State isn't the expected.")
                elif remootio_client.state == State.CLOSED:
                    await remootio_client.trigger_open()

                    await asyncio.wait_for(
                        self.__condition_is_met(self.__is_state_change_listener_invoked, remootio_client,
                                                expected_invoke_count=4),
                        timeout=RemootioClientTestCase.TIMEOUT
                    )

                    self.assertEqual(remootio_client.state, State.OPEN, "State isn't the expected.")

                    await remootio_client.trigger_close()

                    await asyncio.wait_for(
                        self.__condition_is_met(self.__is_state_change_listener_invoked, remootio_client,
                                                expected_invoke_count=6),
                        timeout=RemootioClientTestCase.TIMEOUT
                    )

                    self.assertEqual(remootio_client.state, State.CLOSED, "State isn't the expected.")
            else:
                self.__logger.warning("Further functional tests will be skipped because the Remootio device "
                                      "hasn't a sensor installed.")

    async def __condition_is_met(self, condition_callback: Callable, remootio_client: aioremootio.RemootioClient,
                                 maximum_attempts: int = DEFAULT_MAXIMUM_ATTEMPTS, **kwargs) -> bool:
        result: bool = True

        attempt: int = 1
        while not condition_callback(remootio_client, **kwargs):
            if attempt <= maximum_attempts:
                attempt = attempt + 1
                await asyncio.sleep(RemootioClientTestCase.WAIT_TIME_BETWEEN_ATTEMPTS)
            else:
                result = False

        return result

    def __is_api_version_not_none(self, remootio_client: aioremootio.RemootioClient, **kwargs) -> bool:
        return remootio_client.api_version is not None

    def __is_serial_number_not_none(self, remootio_client: aioremootio.RemootioClient, **kwargs) -> bool:
        return remootio_client.serial_number is not None

    def __is_state_change_listener_invoked(self, remootio_client: aioremootio.RemootioClient, **kwargs) -> bool:
        return self.__state_change_listener.invoke_count == kwargs["expected_invoke_count"]


if __name__ == '__main__':
    unittest.main()
