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
from typing import NoReturn, Optional, Any
import argparse
import logging
import asyncio
import aiohttp
import aioremootio
import datetime

AD_IP_ADDRESS = "ip_address"
AD_API_SECRET_KEY = "api_secret_key"
AD_API_AUTH_KEY = "api_auth_key"
AD_ACTION = "action"
AV_ACTION_TRIGGER = "trigger"
AV_ACTION_OPEN = "open"
AV_ACTION_CLOSE = "close"


class ExampleStateListener(aioremootio.Listener[aioremootio.StateChange]):

    __logger: logging.Logger

    __last_state_change: Optional[datetime.datetime]

    def __init__(self, logger: logging.Logger):
        self.__logger = logger
        self.__last_state_change = None

    async def execute(self, client: aioremootio.RemootioClient, subject: aioremootio.StateChange) -> NoReturn:
        self.__logger.info("State of the device has been changed. IPAddress [%s] OldState [%s] NewState [%s]" %
                           (client.ip_address, subject.old_state, subject.new_state))
        self.__last_state_change = datetime.datetime.now()

    @property
    def last_state_change(self) -> Optional[datetime.datetime]:
        return self.__last_state_change


async def wait_for_state_change(state_change_listener: ExampleStateListener, time: datetime.datetime, logger: logging.Logger):
    while state_change_listener.last_state_change is None or state_change_listener.last_state_change <= time:
        logger.info("Waiting for state change occurred after %s...", time)
        await asyncio.sleep(5)


async def main() -> NoReturn:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    handler: logging.Handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    parser: argparse.ArgumentParser = argparse.ArgumentParser("python %s" % __file__)
    parser.add_argument("--ipAddress", required=True, type=str, dest=AD_IP_ADDRESS,
                        help="IP address of the device to connect to")
    parser.add_argument("--apiSecretKey", required=True, type=str, dest=AD_API_SECRET_KEY,
                        help="API Secret Key for the API access")
    parser.add_argument("--apiAuthKey", required=True, type=str, dest=AD_API_AUTH_KEY,
                        help="API Auth Key for the API access")
    parser.add_argument("--action", required=False, dest=AD_ACTION,
                        choices=[AV_ACTION_TRIGGER, AV_ACTION_OPEN, AV_ACTION_CLOSE],
                        help="The action to be triggered on the device. If not given the state of the device will be "
                             "logged.")
    args: dict = vars(parser.parse_args())

    connection_options: aioremootio.ConnectionOptions = \
        aioremootio.ConnectionOptions(args[AD_IP_ADDRESS], args[AD_API_SECRET_KEY], args[AD_API_AUTH_KEY])

    state_change_listener: ExampleStateListener = ExampleStateListener(logger)

    async with aiohttp.ClientSession() as client_session:
        try:
            async with aioremootio.RemootioClient(
                    connection_options,
                    client_session,
                    aioremootio.LoggerConfiguration(logger=logger),
                    state_change_listener
            ) as remootio_client:
                if AD_ACTION not in args or args[AD_ACTION] is None:
                    logger.info("State of the device: %s", remootio_client.state)
                elif args[AD_ACTION] == AV_ACTION_TRIGGER:
                    await remootio_client.trigger()
                    await wait_for_state_change(state_change_listener, state_change_listener.last_state_change, logger)
                elif args[AD_ACTION] == AV_ACTION_OPEN:
                    await remootio_client.trigger_open()
                    await wait_for_state_change(state_change_listener, state_change_listener.last_state_change, logger)
                elif args[AD_ACTION] == AV_ACTION_CLOSE:
                    await remootio_client.trigger_close()
                    await wait_for_state_change(state_change_listener, state_change_listener.last_state_change, logger)
        except aioremootio.RemootioClientConnectionEstablishmentError:
            logger.exception("The client has failed to establish connection to the Remootio device.")
        except aioremootio.RemootioClientAuthenticationError:
            logger.exception("The client has failed to authenticate with the Remootio device.")
        except aioremootio.RemootioError:
            logger.exception("Failed to create client because of an error.")

if __name__ == "__main__":
    asyncio.run(main())
