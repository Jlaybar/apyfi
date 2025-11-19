from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from apify import Actor
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# --- CONFIGURACIÓN ACTUALIZADA 2025 ---
DEFAULT_POSTAL_CODE = "28002"
IDEALISTA_URL_TEMPLATE = (
    "https://www.idealista.com/geo/venta-viviendas/codigo-postal-{codigo_postal}/con-de-tres-dormitorios/"
)

async def main() -> None:
    async with Actor:
        input_data = await Actor.get_input() or {}
        codigo_postal = str(input_data.get("codigo_postal", DEFAULT_POSTAL_CODE)).strip()[:5]
        if not (codigo_postal.isdigit() and len(codigo_postal) == 5):
            codigo_postal = DEFAULT_POSTAL_CODE

        url = IDEALISTA_URL_TEMPLATE.format(codigo_postal=codigo_postal)
        Actor.log.info(f"Iniciando scrape para CP {codigo_postal}")

        # Proxy residencial español (OBLIGATORIO para Idealista)
        proxy_config = await Actor.create_proxy_configuration(
            groups=['RESIDENTIAL'], 
            country_code='ES'
        )

        async with async_playwright() as p:
            # USAR CHROMIUM CON CANALES REALES (el truco clave 2025)
            browser = await p.chromium.launch_persistent_context(
                user_data_dir="/tmp/playwright-chrome",  # importante para persistencia
                headless=True,
                executable_path=None,  # deja que Playwright use el bundled
                channel="chrome",  # ¡¡ESTO ES CLAVE!! (usa Chrome real, no Chromium genérico)
                proxy=await (await proxy_config.new_proxy_info()).as_playwright_proxy(),
                viewport={"width": 1920, "height": 1080},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                java_script_enabled=True,
                bypass_csp=True,
                # Spoofing avanzado
                has_touch=False,
                is_mobile=False,
                device_scale_factor=1,
                permissions=["geolocation"],
                geolocation={"longitude": -3.703790, "latitude": 40.416775},  # Madrid
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9",
                    "Sec-CH-UA": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                    "Sec-CH-UA-Platform": '"Windows"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Upgrade-Insecure-Requests": "1",
                },
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # --- STEALTH MÁXIMO ---
            await page.add_init_script("""
                // Eliminar rastros de automatización
                delete navigator.__proto__.webdriver;
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [{name: "Chrome PDF Plugin"}, {name: "Chrome PDF Viewer"}]
                });
                Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es'] });
                window.chrome = { runtime: {}, app: {}, loadTimes: () => {} };
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            """)

            try:
                Actor.log.info("Navegando a Idealista...")
                response = await page.goto(url, wait_until="domcontentloaded", timeout=90_000)

                if response.status >= 400:
                    Actor.log.info(f"HTTP {response.status} - Bloqueado o error")
                    await Actor.push_data({
                        "status": "blocked",
                        "status_code": response.status,
                        "codigo_postal": codigo_postal,
                        "url": url
                    })
                    return

                # Esperar a que carguen los anuncios o detectar bloqueo
                try:
                    await page.wait_for_selector(".item", timeout=30_000)
                    Actor.log.info("Anuncios detectados - Acceso exitoso")
                except:
                    # Si no hay .item, probablemente Cloudflare o captcha
                    title = await page.title()
                    if "just a moment" in title.lower() or "cloudflare" in title.lower():
                        Actor.log.warning("Detectado Cloudflare challenge - esperando resolución automática...")
                        await page.wait_for_timeout(15_000)  # a veces se resuelve solo con proxy bueno

                # Scroll suave para cargar todos los anuncios
                await page.evaluate("""
                    async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 300;
                            const timer = setInterval(() => {
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if (totalHeight >= document.body.scrollHeight - window.innerHeight) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 500);
                        });
                    }
                """)

                await asyncio.sleep(5)

                html = await page.content()

                payload = {
                    "status": "success",
                    "html": html,
                    "url": url,
                    "codigo_postal": codigo_postal,
                    "items_count": len(await page.query_selector_all(".item"))
                }

                await Actor.push_data(payload)
                Actor.log.info(f"Scrapeado con éxito - {payload['items_count']} anuncios encontrados")

                # Guardar en JSON local
                os.makedirs(f"data/casa/{codigo_postal}", exist_ok=True)
                with open(f"data/casa/{codigo_postal}/scraped_data_{codigo_postal}.json", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=4)

            except Exception as e:
                Actor.log.exception(f"Error inesperado: {e}")
                await Actor.push_data({"status": "error", "error": str(e)})
            finally:
                await browser.close()


if __name__ == "__main__":
    asyncio.run(main())