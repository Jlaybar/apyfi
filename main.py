import asyncio
from apify import Actor
from playwright.async_api import async_playwright

async def main():
    async with Actor:
        input_data = await Actor.get_input() or {}
        CODIGO_POSTAL = input_data.get("codigo_postal", "28002")
        URL = f"https://www.idealista.com/geo/venta-viviendas/codigo-postal-{CODIGO_POSTAL}/con-de-tres-dormitorios/pagina-1"

        await Actor.log.info(f"Iniciando scrape para CP {CODIGO_POSTAL}...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                proxy={"server": "http://proxy.apify.com:8000"}
            )
            page = await context.new_page()

            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                window.chrome = { runtime: {} };
            """)

            await page.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9",
                "Sec-CH-UA": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                "Sec-CH-UA-Platform": '"Windows"'
            })

            try:
                response = await page.goto(URL, wait_until="networkidle", timeout=60000)
                if response.status >= 400:
                    await Actor.push_data({"error": f"HTTP {response.status}", "url": URL})
                    return

                await page.wait_for_selector(".items-container", timeout=20000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

                html = await page.content()
                await Actor.push_data({
                    "codigo_postal": CODIGO_POSTAL,
                    "url": URL,
                    "html": html,
                    "status": "success"
                })
                await Actor.log.info("ÉXITO")

            except Exception as e:
                await Actor.push_data({"error": str(e), "url": URL})
            finally:
                await browser.close()

if __name__ == "__main__":
    asyncio.run(main())