from __future__ import annotations

import asyncio
from typing import Any

from apify import Actor
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

load_dotenv()

DEFAULT_POSTAL_CODE = "28002"
IDEALISTA_URL_TEMPLATE = (
    "https://www.idealista.com/geo/venta-viviendas/"
    "codigo-postal-{codigo_postal}/con-de-tres-dormitorios/pagina-1"
)
ITEMS_SELECTOR = ".items-container"
SCROLL_DELAY_SECONDS = 2
PAGE_TIMEOUT_MS = 60_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Sec-CH-UA": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
    "Sec-CH-UA-Platform": '"Windows"',
}


def _resolve_postal_code(input_data: dict[str, Any]) -> str:
    """Valida el codigo postal recibido y aplica un valor por defecto si es necesario."""
    raw_value = str(input_data.get("codigo_postal", DEFAULT_POSTAL_CODE)).strip()
    if len(raw_value) == 5 and raw_value.isdigit():
        return raw_value

    Actor.log.warning(
        f"Codigo postal invalido en el input. Se utilizara el valor por defecto {DEFAULT_POSTAL_CODE}."
    )
    return DEFAULT_POSTAL_CODE


async def _get_proxy_url() -> str | None:
    try:
        proxy_config = await Actor.create_proxy_configuration()
        return await proxy_config.new_url()
    except Exception as error:
        Actor.log.warning(
            f"No se pudo inicializar Apify Proxy automaticamente: {error}"
        )
        return None


async def _prepare_page(page: Page) -> None:
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {} };
        """
    )
    await page.set_extra_http_headers(HEADERS)


async def _scrape_postal_code(codigo_postal: str) -> None:
    url = IDEALISTA_URL_TEMPLATE.format(codigo_postal=codigo_postal)
    Actor.log.info(f"Iniciando scrape para CP {codigo_postal}")

    async with async_playwright() as playwright:
        proxy_url = await _get_proxy_url()
        browser = await playwright.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()
        await _prepare_page(page)

        try:
            response = await page.goto(
                url,
                wait_until="networkidle",
                timeout=PAGE_TIMEOUT_MS,
            )
            if response is None:
                raise RuntimeError("No se recibio respuesta HTTP inicial.")
            if response.status >= 400:
                Actor.log.warning(
                    f"Respuesta HTTP {response.status} durante la carga de {url}"
                )
                await Actor.push_data(
                    {
                        "codigo_postal": codigo_postal,
                        "url": url,
                        "status": "http_error",
                        "status_code": response.status,
                    }
                )
                return

            await page.wait_for_selector(ITEMS_SELECTOR, timeout=20_000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(SCROLL_DELAY_SECONDS)

            html = await page.content()
            await Actor.push_data(
                {
                    "codigo_postal": codigo_postal,
                    "url": url,
                    "status": "success",
                    "html": html,
                }
            )
            Actor.log.info(f"Scrape completado para {codigo_postal}")

        except Exception as error:
            Actor.log.error(f"Error durante el scrape: {error}")
            await Actor.push_data(
                {
                    "codigo_postal": codigo_postal,
                    "url": url,
                    "status": "error",
                    "error": str(error),
                }
            )
        finally:
            await context.close()
            await browser.close()


async def main() -> None:
    async with Actor:
        input_data = await Actor.get_input() or {}
        codigo_postal = _resolve_postal_code(input_data)
        await _scrape_postal_code(codigo_postal)


if __name__ == "__main__":
    asyncio.run(main())
