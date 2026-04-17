"""Start parsing function.

Keyword Arguments:
- R: Region example (en, cn, kz)
- L: Language Example (en, ru, ch)
- I: File with ID
Returns: Return_Description

"""


from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
from pathlib import Path

import aiocsv
import aiofiles
import aiohttp

from SieportalGetTreeApi import SieportalTreeAPI
from SieportalPagination import Pagination

logger = logging.getLogger("MainLogger")


def parse_args() ->  argparse.Namespace:
    """Parishes the command line arguments."""
    parser = argparse.ArgumentParser(description="Sieportal data extraction tool")

    parser.add_argument(
        "--input", "-i", default="files/key.csv", help="Input CSV file with node IDs",
    )

    parser.add_argument(
        "--language", "-l", default="en", help="Language code (e.g., en, de, fr)",
    )

    parser.add_argument(
        "--region", "-r", default="kr", help="Region code (e.g., kr, us, de)",
    )

    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.1,
        help="Delay between requests in seconds",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="DEBUG",
        help="Logging level",
    )

    return parser.parse_args()


async def read(fp: str) -> AsyncGenerator[str]:
    """Read - takes to the input the path to the file and simply runs out line.

    Args:
        fp (str): the path to the file.

    Returns:
        AsyncGenerator [str]: Return generator with article.

    Yields:
        Iterator [asyncgenerator [str]]: Return generator with article.

    """
    async with aiofiles.open(fp, newline="") as file:
        reader = aiocsv.AsyncReader(file)

        async for line in reader:
            yield line[0]


async def parsing() -> None: # noqa: C901
    """Start parsing function."""
    args = parse_args()
    logging.basicConfig(
        filename=f"logs\\log-{args.language}-{args.region}.log",
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    output_dir = Path(f"files")
    if output_dir and not output_dir.exists():
        fp = Path(output_dir)
        fp.mkdir(parents=True)
        fp = fp / f"{args.language}-{args.region}.csv"
    else:
        fp = output_dir / f"{args.language}-{args.region}.csv"

    async with aiofiles.open(
        fp, "a", newline="",
    ) as file:
        writer = aiocsv.AsyncWriter(file)
        async with aiohttp.ClientSession() as session:
            # Аномалия 10000083, 10000800
            sie = SieportalTreeAPI(session, args.language, args.region)
            tasks = []

            async for node_id in read(args.input):
                
                tasks.append(
                    asyncio.create_task(sie.get_tree_information(node_id))
                )
                if len(tasks) >= 10:
                    for data in await asyncio.gather(*tasks):
                        if data is None:
                            continue

                        logger.info(
                            "Found products: %s, accessories %s - [%s]",
                            data["variants"],
                            data["product"],
                            node_id,
                        )
                        if data["variants"]:
                            pagination = await Pagination.create(
                                node_id, sie, SieportalTreeAPI.get_products,
                            )
                            if pagination is not None:
                                async for page in pagination.fetch_all():
                                    if page is None:
                                        continue
                                    await writer.writerows(
                                        [[x.article, x.url] for x in page.items],
                                    )

                        if data["product"]:
                            pagination = await Pagination.create(
                                node_id, sie, SieportalTreeAPI.get_accesories,
                            )
                            if pagination is None:
                                continue
                            async for page in pagination.fetch_all():
                                if page is not None:
                                    await writer.writerows(
                                        [[x.article, x.url] for x in page.items],
                                    )
            if tasks:
                for data in await asyncio.gather(*tasks):
                    if data is None:
                        continue

                    logger.info(
                        "Found products: %s, accessories %s - [%s]",
                        data["variants"],
                        data["product"],
                        node_id,
                    )
                    if data["variants"]:
                        pagination = await Pagination.create(
                            node_id, sie, SieportalTreeAPI.get_products,
                        )
                        if pagination is not None:
                            async for page in pagination.fetch_all():
                                if page is None:
                                    continue
                                await writer.writerows(
                                    [[x.article, x.url] for x in page.items],
                                )
                    if data["product"]:
                        pagination = await Pagination.create(
                            node_id, sie, SieportalTreeAPI.get_accesories,
                        )
                        if pagination is None:
                            continue
                        async for page in pagination.fetch_all():
                            if page is not None:
                                await writer.writerows(
                                    [[x.article, x.url] for x in page.items],
                                )


if __name__ == "__main__":
    asyncio.run(parsing())
