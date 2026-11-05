"""The shell and a module's pages in a real browser, signed in as the admin."""

from __future__ import annotations

lazy import re

from playwright.async_api import Page, async_playwright, expect
from served import Served, serving


async def signed_in(page: Page, served: Served) -> Page:
    await page.goto(f"{served.url}/stall")
    await page.wait_for_url(re.compile(r"/login/$"))
    await page.fill("#name", "admin")
    await page.fill("#password", served.password)
    await page.click("button[type=submit]")
    await page.wait_for_url(re.compile(r"/overview$"))
    return page


async def test_a_module_page_wears_the_shell_theme_and_language_and_moves_its_address():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN", color_scheme="dark")
            page = await signed_in(await context.new_page(), served)
            root = page.locator("html")
            # an account that chose nothing follows the system and the browser
            await expect(root).to_have_attribute("data-theme", "night")
            await expect(root).to_have_attribute("lang", "zh-CN")
            await page.goto(f"{served.url}/stall")
            module = page.frame_locator("iframe.frame")
            await expect(module.locator("#language")).to_have_text("zh-CN")
            await expect(module.locator("html")).to_have_attribute(
                "data-theme", "night"
            )
            await expect(module.locator("html")).to_have_attribute("lang", "zh-CN")
            await module.locator("#next").click()
            await page.wait_for_url(re.compile(r"/stall/second$"))
            await expect(page).to_have_title("Second stall")
            await expect(page.locator("[data-title]")).to_have_text("Second stall")
            await page.go_back()
            await page.wait_for_url(re.compile(r"/stall$"))
            await expect(page).to_have_title("First stall")

            light = await (
                await browser.new_context(
                    storage_state=await context.storage_state(),
                    locale="en-US",
                    color_scheme="light",
                )
            ).new_page()
            await light.goto(f"{served.url}/stall")
            await expect(light.locator("html")).to_have_attribute("data-theme", "day")
            await expect(light.locator("html")).to_have_attribute("lang", "en")
            framed = light.frame_locator("iframe.frame")
            await expect(framed.locator("#language")).to_have_text("en")
            await expect(framed.locator("html")).to_have_attribute("data-theme", "day")
        finally:
            await browser.close()


async def test_overview_content_is_as_tall_as_its_page():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(color_scheme="light")
            page = await signed_in(await context.new_page(), served)
            overview = page.frame(url=re.compile(r"/ui/overview/"))
            assert overview is not None
            tile = (
                "document.querySelector('.tile iframe').getBoundingClientRect().height"
            )
            await overview.wait_for_function(f"{tile} >= 240")
            await (
                page.frame_locator("iframe.frame")
                .frame_locator(".tile iframe")
                .locator("#more")
                .click()
            )
            await overview.wait_for_function(f"{tile} >= 480")
        finally:
            await browser.close()


async def test_times_are_read_on_the_clock_of_the_browser():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(timezone_id="America/New_York")
            page = await signed_in(await context.new_page(), served)
            await page.goto(f"{served.url}/stall")
            # the module's first page is drawn with the zone the shell left
            moment = page.frame_locator("iframe.frame").locator("#moment")
            await expect(moment).to_have_text("2026-07-06 08:00:00")
        finally:
            await browser.close()


async def test_logging_out_returns_to_the_login_page():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context()
            page = await signed_in(await context.new_page(), served)
            await page.click(".me .icon-btn")
            await page.wait_for_url(re.compile(r"/login/$"))
            await page.goto(f"{served.url}/overview")
            await page.wait_for_url(re.compile(r"/login/$"))
        finally:
            await browser.close()


async def test_a_narrow_screen_gets_one_column_and_a_bar_along_the_bottom():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(
                locale="zh-CN",
                color_scheme="dark",
                viewport={"width": 390, "height": 844},
            )
            page = await context.new_page()
            await page.goto(f"{served.url}/overview")
            await page.wait_for_url(re.compile(r"/login/$"))
            # the form first, the street below it
            await expect(page.locator(".band")).to_be_visible()
            await expect(page.locator(".art")).to_be_hidden()
            size = await page.locator("#name").evaluate(
                "field => parseFloat(getComputedStyle(field).fontSize)"
            )
            assert size >= 16
            await page.fill("#name", "admin")
            await page.fill("#password", served.password)
            await page.click("button[type=submit]")
            await page.wait_for_url(re.compile(r"/overview$"))

            bar = page.locator(".side")
            box = await bar.bounding_box()
            assert box is not None
            assert box["y"] + box["height"] >= 844 - 2
            await expect(page.locator(".side .brand")).to_be_hidden()
            # seven places do not fit: the rest, settings among them, wait behind More
            settings = page.locator('.overflow a[href="/settings"]')
            await expect(settings).to_be_hidden()
            # More opens from the keyboard as well as by touch
            await page.focus("#more-places")
            await page.keyboard.press("Space")
            await expect(settings).to_be_visible()
            await settings.click()
            await page.wait_for_url(re.compile(r"/settings$"))

            # settings sits behind More, which stays lit while it shows
            await expect(page.locator(".side .more")).to_have_class(
                re.compile(r"\bon\b")
            )
            frame = page.frame_locator("iframe.frame")
            await expect(frame.locator(".settings")).to_have_attribute(
                "data-view", "directory"
            )
            await expect(frame.locator(".snav .gp")).to_have_text("个人")
            await expect(frame.locator(".leave")).to_be_visible()
            back = page.locator("[data-back-link]")
            await expect(back).to_be_hidden()
            await frame.locator('.snav a[href="/ui/settings/stall"]').click()
            await page.wait_for_url(re.compile(r"/settings/stall$"))
            await expect(back).to_be_visible()
            await back.click()
            await page.wait_for_url(re.compile(r"/settings$"))
        finally:
            await browser.close()


async def test_a_framed_page_lays_out_as_the_shell_around_it_does():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            # wide enough for the sidebar, which leaves the frame under 960 pixels
            context = await browser.new_context(viewport={"width": 1100, "height": 800})
            page = await signed_in(await context.new_page(), served)
            await page.goto(f"{served.url}/settings/stall")
            frame = page.frame_locator("iframe.frame")
            await expect(frame.locator("html")).to_have_attribute("data-layout", "wide")
            await expect(frame.locator(".snav")).to_be_visible()
            # the window narrows: the page and the shell's way back change together
            await page.set_viewport_size({"width": 390, "height": 844})
            await expect(frame.locator("html")).to_have_attribute(
                "data-layout", "narrow"
            )
            await expect(frame.locator(".snav")).to_be_hidden()
            await expect(page.locator("[data-back-link]")).to_be_visible()
        finally:
            await browser.close()
