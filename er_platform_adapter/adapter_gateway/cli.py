from __future__ import annotations

import logging

import click
import uvicorn

from .app import create_app
from .config import GatewayServerConfig


@click.command()
@click.option("--dotenv", default=".env.server", show_default=True, type=click.Path(dir_okay=False))
@click.option("--host", default=None, help="Override ADAPTER_GATEWAY_HOST.")
@click.option("--port", default=None, type=click.IntRange(1, 65535), help="Override ADAPTER_GATEWAY_PORT.")
@click.option("-v", "--verbose", is_flag=True)
def main(dotenv: str, host: str | None, port: int | None, verbose: bool) -> None:
    """Run the public Adapter-to-IM control gateway."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    config = GatewayServerConfig.load(dotenv)
    errors = config.validate()
    if errors:
        raise click.ClickException("; ".join(errors))
    app = create_app(config)
    uvicorn.run(
        app,
        host=host or config.host,
        port=port or config.port,
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips=["127.0.0.1", "::1"],
    )


if __name__ == "__main__":
    main()
