"""Sieportal API client implementation."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass

import aiohttp
import dotenv

from SieportalTyping import Child, PageResult, Product

# Константы после импортов
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_400_BAD_REQUEST = 400
HTTP_500_INTERNAL_ERROR = 500
HTTP_600_MAX = 600

logger = logging.getLogger(__name__)
dotenv.load_dotenv()

@dataclass
class Config:
    """Complete config for data management."""

    sleep_time: int = 3
    proxy_list: list[str] = None
    client_data: dict[str, str] = None

    def __post_init__(self) -> None:
        """Data validation."""
        if self.proxy_list is None:
            self.proxy_list = [os.getenv("PROXY")]
        if self.client_data is None:
            self.client_data = {
                "client_id": "Siemens.SiePortal.UI",
                "client_secret": os.getenv("CLIENT_SECRET"),
                "grant_type": "client_credentials",
            }


class SieportalAPI:
    TOKEN_URL = (
        "https://auth.sieportal.siemens.com/connect/token"
    )

    def __init__(
        self,
        session: aiohttp.ClientSession,
        language: str,
        region_id: str,
        *,
        max_try: int = 3,
        config: Config | None = None,
    ) -> None:
        self.max_try = max_try
        if config is None:
            self.config = Config()
        else:
            self.config = config
        self._session = session
        self.language = language
        self.region = region_id

        self._token = None

    async def fetch(
        self,
        method: str,
        url: str,
        *args: str,
        **kwargs: dict[str, str | dict[str, str]],
    ) -> dict:
        for try_num in range(1, self.max_try + 1):
            headers = kwargs.get("headers", {})
            headers["authorization"] = self._token or await self._get_token()
            kwargs["headers"] = headers

            try:
                async with self._session.request(
                    method, url, *args, **kwargs,
                ) as response:
                    response.raise_for_status()
                    logger.debug("Status 200 for - %s", url)
                    return await response.json()
            except aiohttp.ClientResponseError as error:
                if error.status == HTTP_401_UNAUTHORIZED:
                    logger.info("Outdated/non -working token we update ...")
                    async with self._session.post(
                        self.TOKEN_URL, data=self.config.client_data,
                    ) as response:
                        response.raise_for_status()
                        self._token = await self._get_token()
                    await asyncio.sleep(self.config.sleep_time * try_num)
                    continue

                if error.status == HTTP_403_FORBIDDEN:
                    kwargs["proxy"] = random.choice(self.config.proxy_list)
                    logger.warning(
                        "Inaccessible SID!I use proxy - %s",
                        kwargs["proxy"],
                    )
                    await asyncio.sleep(self.config.sleep_time * try_num)

                    continue

                if HTTP_500_INTERNAL_ERROR < error.status < HTTP_500_INTERNAL_ERROR + 100:
                    logger.info(
                        "The problem of the server is waiting for ... - Trying %d - %d",
                        try_num,
                        error.status,
                    )
                    await asyncio.sleep(self.config.sleep_time)
                    continue

                if error.status == HTTP_400_BAD_REQUEST:
                    logger.info("Unknown data type")
                    return None

                if error.status == HTTP_500_INTERNAL_ERROR:
                    logger.info("There is no data ...")
                    return None

                logger.exception("Inexpedient status: %s", error.status)
                return None
            except Exception as error:
                logger.exception("Unknown error: %s", error)

        logger.warning("Could not reach the server for %s of attempts", self.max_try)
        return None

    async def _get_token(self) -> str:
        """Obtaining a token of authorization."""
        while True:
            try:
                async with self._session.post(
                    self.TOKEN_URL, data=self.config.client_data,
                ) as response:
                    response.raise_for_status()
                    token_data = await response.json()
                    return f"Bearer {token_data['access_token']}"
            except Exception as e:
                logger.exception("Token Error: %s", e)


class SieportalTreeAPI(SieportalAPI):
    """Main API class for Sieportal connection."""

    GET_TREE_CHILDREN = (
        "https://sieportal.siemens.com/api/mall/CatalogTreeApi/GetTreeChildren"
    )
    GET_PRODUCTS = (
        "https://sieportal.siemens.com/api/mall/CatalogTreeApi/GetNodeProducts"
    )
    GET_ACCESORIES = (
        "https://sieportal.siemens.com/api/mall/CatalogTreeApi/GetProductAccessories"
    )
    GET_INFORMATION = (
        "https://sieportal.siemens.com/api/mall/CatalogTreeApi/GetNodeInformation"
    )

    def __init__(
        self,
        session: aiohttp.ClientSession,
        language: str,
        region_id: str,
        *,
        max_try: int = 3,
        config: Config | None = None
        ) -> None:
        """Initialize Sieportal API client.

        Args:
            session: aiohttp client session
            language: API language
            region_id: Region identifier
            max_try: Maximum retry attempts
            config: Configuration object

        """
        super().__init__(session, language, region_id, max_try=max_try, config=config)

    async def get_tree_children(self, node_id: int | str) -> PageResult[Child] | None:
        """He takes out from the branch of children."""
        params = {
            "ClassificationScheme": "CatalogTree",
            "NodeId": node_id,
            "IsCatalogPage": "true",
            "RegionId": self.region,
            "CountryCode": self.region,
            "Language": self.language,
        }
        response = (await self.fetch("GET", self.GET_TREE_CHILDREN, params=params))[
            "catalogTreeChildNodes"
        ]
        if response is None:
            return None

        table = [Child(*data.values()) for data in response]
        return PageResult(table, len(table))

    async def get_tree_information(self, node_id: int | str) -> dict[str, bool] | None:
        """Take out information about the branch."""
        params = {
            "NodeId": node_id,
            "RegionId": self.region,
            "TreeName": "CatalogTree",
            "Language": self.language,
        }
        response = await self.fetch("GET", self.GET_INFORMATION, params=params)
        if response is None:
            return None

        return {
            "info": response.get("containsProductInformation", False),
            "variants": response.get("containsProductVariants", False),
            "product": response.get("containsRelatedProducts", False),
        }

    async def get_products(
        self,
        node_id: int | str,
        page: int = 0,
        ) -> PageResult[Product] | None:
        """Return the number of products in the indicated investment."""
        json_data = {
            "technicalSelectionFilters": [],
            "nodeId": node_id,
            "treeName": "CatalogTree",
            "pageNumberIndex": page,
            "limit": 50,
            "checkStockAvailability": False,
            "keywordFilter": None,
            "regionId": self.region,
            "language": self.language,
            "sortCategory": "Newest",
        }

        response = await self.fetch("POST", self.GET_PRODUCTS, json=json_data)
        if response is None:
            return None
        product_count = response["productCount"]

        return PageResult(
            [
                Product(article=product["articleNumber"], url=product.get("url"))
                for product in response.get("products", [])
            ],
            product_count,
        )

    async def get_accesories(
        self,
        node_id: int,
        page: int = 0,
        ) -> PageResult[Product] | None:
        """Return values from add goods."""
        json_data = {
            "regionId": self.region,
            "language": self.language,
            "nodeId": node_id,
            "treeName": "CatalogTree",
            "pageNumberIndex": page,
            "limit": 50,
            "technicalSelectionFilters": [],
        }

        response = await self.fetch("POST", self.GET_ACCESORIES, json=json_data)
        if response is None:
            return None
        product_count = response["productCount"]
        return PageResult(
            [
                Product(article=product["articleNumber"], url=product.get("url"))
                for product in response.get("products", [])
            ],
            product_count,
        )
