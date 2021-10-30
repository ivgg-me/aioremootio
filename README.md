# aioremootio - An asynchronous API client library for Remootio

_aioremootio_ is an asynchronous API client library for [Remootio](https://remootio.com/) written in Python 3 and 
based on [asyncio](https://docs.python.org/3/library/asyncio.html) and [aiohttp](https://pypi.org/project/aiohttp/).

## Supported functionalities of the device

With this client library is currently possible to listen to state changes of a [Remootio](https://remootio.com/) device, 
to listen to some events triggered by it, furthermore to operate the gate or garage door connected to it.

This client library supports currently the listening to following kind of events triggered by the device:
* `STATE_CHANGE` which is triggered by the device when its state changes
* `RELAY_TRIGGER` which is triggered by the device when its control output has been triggered to operate the 
  connected gate or garage door
* `LEFT_OPEN` which is triggered by the device when the connected gate or garage door has been left open
* `RESTART` which is triggered by the device when it was restarted

## Using the library

The following example demonstrates how you can use this library.

```python
from typing import NoReturn
import logging
import asyncio
import aiohttp
import aioremootio

class ExampleStateListener(aioremootio.Listener[aioremootio.StateChange]):

    __logger: logging.Logger

    def __init__(self, logger: logging.Logger):
        self.__logger = logger

    async def execute(self, client: aioremootio.RemootioClient, subject: aioremootio.StateChange) -> NoReturn:
        self.__logger.info("State of the device has been changed. IPAddress [%s] OldState [%s] NewState [%s]" %
                           (client.ip_address, subject.old_state, subject.new_state))


async def main() -> NoReturn:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    handler: logging.Handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    
    connection_options: aioremootio.ConnectionOptions = \
        aioremootio.ConnectionOptions("192.168.0.1", "API_SECRET_KEY", "API_AUTH_KEY")

    state_change_listener: aioremootio.Listener[aioremootio.StateChange] = \
        ExampleStateListener(logger)

    remootio_client: aioremootio.RemootioClient

    async with aiohttp.ClientSession() as client_session:
        try:
            remootio_client = \
                await aioremootio.RemootioClient(
                    connection_options,
                    client_session,
                    aioremootio.LoggerConfiguration(logger=logger),
                    state_change_listener
                )
        except aioremootio.RemootioClientConnectionEstablishmentError:
            logger.exception("The client has failed to establish connection to the Remootio device.")
        except aioremootio.RemootioClientAuthenticationError:
            logger.exception("The client has failed to authenticate with the Remootio device.")
        except aioremootio.RemootioError:
            logger.exception("Failed to create client because of an error.")
        else:
            logger.info("State of the device: %s", remootio_client.state)
            
            if remootio_client.state == aioremootio.State.NO_SENSOR_INSTALLED:
                await remootio_client.trigger()
            else:
                await remootio_client.trigger_open()
                await remootio_client.trigger_close()            

        while True:
            await asyncio.sleep(0.1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

To get the _API Secret Key_ and _API Auth Key_ of your [Remootio](https://remootio.com/) device you must enable the 
API on it according to the 
[Remootio Websocket API documentation](https://github.com/remootio/remootio-api-documentation). 

## Running the bundled examples

The [project source](https://github.com/ivgg-me/aioremootio) does also contain two examples.

The example [`example.py`](https://github.com/ivgg-me/aioremootio/blob/master/example.py) demonstrates how you can 
use the client as a Python object.

The example [`example_acm.py`](https://github.com/ivgg-me/aioremootio/blob/master/example_acm.py) demonstrates how 
you can use the client as an asynchronous context manager.

To run the bundled examples you must 
1. also enable the API on your [Remootio](https://remootio.com/) device to get the _API Secret Key_ and _API Auth 
   Key_ of it, and
2. add the source folder [`/src`](https://github.com/ivgg-me/aioremootio/tree/master/src) of the repository to your 
   `PYTHONPATH`.

After the two steps described above you can run the bundled examples with the argument `--help` to show 
the usage information. E.g.:

```commandline
python example.py --help
```

## Running the bundled tests

To run the bundled tests you must create the `.\remootio_devices.configuration.json` file with a content according 
to the following template.

```
{
    "ip_address": "IP-ADDRESS-OF-YOUR-DEVICE",
    "api_secret_key": "API-SECRET-KEY-OF-YOUR-DEVICE",
    "api_auth_key": "API-AUTH-KEY-OF-YOUR-DEVICE",
    "api_version": API-VERSION-OF-YOUR-DEVICE
}
```

---

Copyright &copy; 2021 Gergö Gabor Ilyes-Veisz. 
Licensed under the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0)