from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from apify import Actor
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

# Carga variables de entorno desde .env
load_dotenv()

# --- CONFIGURACIÓN ---
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
    raw_value = str(input_data.get("codigo_postal", DEFAULT_POSTAL_CODE)).strip()
    if len(raw_value) == 5 and raw_value.isdigit():
        return raw_value
    Actor.log.warning(
        f"Codigo postal invalido en el input. Se utilizara el valor por defecto {DEFAULT_POSTAL_CODE}."
    )
    return DEFAULT_POSTAL_CODE


async def _prepare_page(page: Page) -> None:
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {} };
        """
    )
    await page.set_extra_http_headers(HEADERS)


async def save_json_file(codigo_postal: str, data: dict[str, Any]) -> None:
    try:
        target_dir = os.path.join("data", "casa", codigo_postal)
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, f"scraped_data_{codigo_postal}.json")
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        Actor.log.info(f"Archivo JSON guardado en: {filepath}")
    except Exception as error:
        Actor.log.error(f"Error al guardar archivo JSON: {error}")



async def _scrape_postal_code(codigo_postal: str) -> None:
    url = IDEALISTA_URL_TEMPLATE.format(codigo_postal=codigo_postal)
    Actor.log.info(f"Iniciando scrape para CP {codigo_postal}")

    # --- VERIFICACIÓN DEL TOKEN ---
    token = os.getenv("APIFY_TOKEN")
    Actor.log.info(f"APIFY_TOKEN: {'Encontrado' if token else 'NO encontrado'}")

    # --- INICIALIZAR proxy_config SIEMPRE ---
    proxy_config = None

    if token:
        try:
            proxy_config = await Actor.create_proxy_configuration(
                groups=['RESIDENTIAL'],
                country_code='ES'
            )
            Actor.log.info("Proxy RESIDENTIAL (ES) configurado con éxito")
        except Exception as e:
            Actor.log.warning(f"Proxy no disponible: {e}. Continuando sin proxy.")
    else:
        Actor.log.warning("Sin APIFY_TOKEN → sin proxy → alto riesgo de 403")

    # --- PLAYWRIGHT ---
    async with async_playwright() as playwright:
        launch_options = {"headless": True}

        # Solo añade proxy si se creó correctamente
        if proxy_config:
            launch_options["proxy"] = proxy_config
        else:
            Actor.log.info("Navegando sin proxy (riesgo de bloqueo)")

        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()
        await _prepare_page(page)

        try:
            response = await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT_MS)
            if not response:
                raise RuntimeError("Sin respuesta del servidor")

            status_code = response.status
            Actor.log.info(f"Respuesta HTTP: {status_code}")

            if status_code >= 400:
                payload = {
                    "codigo_postal": codigo_postal,
                    "url": url,
                    "status": "http_error",
                    "status_code": status_code,
                }
            else:
                await page.wait_for_selector(ITEMS_SELECTOR, timeout=20_000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(SCROLL_DELAY_SECONDS)
                html = await page.content()
                payload = {
                    "codigo_postal": codigo_postal,
                    "url": url,
                    "status": "success",
                    "html": html,
                }
                Actor.log.info("Scrape exitoso: HTML obtenido")

            await Actor.push_data(payload)
            await save_json_file(codigo_postal, payload)

        except Exception as error:
            Actor.log.error(f"Error durante el scrape: {error}")
            payload = {
                "codigo_postal": codigo_postal,
                "url": url,
                "status": "error",
                "error": str(error),
            }
            await Actor.push_data(payload)
            await save_json_file(codigo_postal, payload)

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


