"""Command line entry point: ``python3 -m spiderd <command>``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

from . import __version__
from .auth import Authenticator, owrx_data_directory
from .config import Config
from .server import LogBuffer, SpiderServer

log = logging.getLogger("spiderd")


def _paths(args):
    config_file = os.path.join(args.data_dir, "config.json")
    owrx_users = args.owrx_users or os.path.join(owrx_data_directory(args.owrx_etc), "users.json")
    return config_file, owrx_users


def cmd_run(args) -> int:
    log_buffer = LogBuffer()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(log_buffer)
    config_file, owrx_users = _paths(args)
    config = Config(config_file).load()
    if not os.path.exists(config_file):
        config.save()
        log.info("created default configuration %s", config_file)
    if args.port:
        config.data["server"]["port"] = args.port
    auth = Authenticator(owrx_users)
    if auth.accounts_state() == "unreadable":
        log.warning("cannot read the OpenWebRX+ accounts in %s yet: the admin page accepts only "
                    "OpenWebRX+ administrators, so spiderd must run as the OpenWebRX+ user", owrx_users)

    async def main() -> None:
        server = SpiderServer(config, auth, log_buffer)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        await server.start()
        await stop.wait()
        log.info("stopping")
        await server.stop()

    asyncio.run(main())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="spiderd", description="DX cluster spots for OpenWebRX+")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", default=os.environ.get("SPIDERD_DATA_DIR", "/var/lib/owrx-spider"),
                        help="where config.json is stored (default: %(default)s)")
    parser.add_argument("--owrx-etc", default="/etc/openwebrx",
                        help="OpenWebRX+ configuration directory, used to find users.json")
    parser.add_argument("--owrx-users", default=os.environ.get("SPIDERD_OWRX_USERS", ""),
                        help="explicit path to the OpenWebRX+ users.json")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run the service (default)")
    run.add_argument("--port", type=int, default=0, help="override the listening port")
    run.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    run.set_defaults(func=cmd_run)


    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(list(argv or sys.argv[1:]) + ["run"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
