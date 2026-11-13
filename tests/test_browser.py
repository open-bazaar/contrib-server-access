"""The shell and a module's pages in a real browser, signed in as the admin."""

from __future__ import annotations

lazy import asyncio
lazy import re

from playwright.async_api import Page, async_playwright, expect
from served import Served, serving


async def signed_in(page: Page, served: Served) -> Page:
    await page.goto(f"{served.url}/stall")
    await page.wait_for_url(re.compile(r"/login/$"))
    await page.fill("#name", "admin")
    await page.fill("#password", served.password)
    await page.click("button[type=submit]")
    await page.wait_for_url(re.compile(r"/stall$"))
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
            # the page draws its own top bar
            await expect(module.locator(".top h1")).to_have_text("Second stall")
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


async def test_the_shell_stays_as_its_places_open_and_its_pages_change_in_place():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN")
            page = await signed_in(await context.new_page(), served)
            await page.evaluate("window.kept = true")
            lit = page.locator('.side a.nav[aria-current="page"]')
            # a place in the sidebar opens in the frame, lit, the shell kept
            await page.locator('.side a.nav[href="/stall/aisle/1"]').click()
            await page.wait_for_url(re.compile(r"/stall/aisle/1$"))
            await expect(lit).to_have_attribute("href", "/stall/aisle/1")
            await page.locator('.side a.nav[href="/stall"]').click()
            await page.wait_for_url(re.compile(r"/stall$"))
            await expect(lit).to_have_attribute("href", "/stall")
            # a page's own link changes it in place, its address following
            module = page.frame(url=re.compile(r"/ui/stall/$"))
            assert module
            await module.evaluate("window.kept = true")
            await module.click("#next")
            await page.wait_for_url(re.compile(r"/stall/second$"))
            await expect(page).to_have_title("Second stall")
            assert await module.evaluate("window.kept === true")
            # back to where it was, the place lit as the frame goes
            await page.go_back()
            await page.wait_for_url(re.compile(r"/stall$"))
            await expect(page).to_have_title("First stall")
            await page.go_back()
            await page.wait_for_url(re.compile(r"/stall/aisle/1$"))
            await expect(lit).to_have_attribute("href", "/stall/aisle/1")
            assert await page.evaluate("window.kept === true")
        finally:
            await browser.close()


async def test_a_framed_part_is_as_tall_as_its_page():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(color_scheme="light")
            page = await signed_in(await context.new_page(), served)
            await page.goto(f"{served.url}/settings/stall")
            await page.wait_for_url(re.compile(r"/settings/stall$"))
            settings = page.frame(url=re.compile(r"/ui/settings/stall"))
            assert settings is not None
            pane = (
                "document.querySelector('iframe.pane').getBoundingClientRect().height"
            )
            await settings.wait_for_function(f"{pane} >= 240")
            await (
                page.frame_locator("iframe.frame")
                .frame_locator("iframe.pane")
                .locator("#more")
                .click()
            )
            await settings.wait_for_function(f"{pane} >= 480")
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
            await page.goto(f"{served.url}/settings")
            await page.frame_locator("iframe.frame").locator(".leave").click()
            await page.wait_for_url(re.compile(r"/login/$"))
            await page.goto(f"{served.url}/stall")
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
            await page.goto(f"{served.url}/stall")
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
            await page.wait_for_url(re.compile(r"/stall$"))

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
            await expect(frame.locator(".snav .gp").first).to_have_text("个人")
            await expect(frame.locator(".leave")).to_be_visible()
            back = frame.locator(".top .back")
            await expect(back).to_have_count(0)
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
            await expect(frame.locator(".top .back")).to_be_visible()
        finally:
            await browser.close()


async def test_with_a_login_method_the_card_turns_between_it_and_the_password():
    async with serving(door=True) as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            page = await (await browser.new_context(locale="zh-CN")).new_page()
            await page.goto(f"{served.url}/login/")
            card = page.locator(".method")
            await expect(card.locator(".logo.big")).to_be_visible()
            await expect(card.locator("#password")).to_be_hidden()
            await card.locator(".corner").click()
            await expect(card.locator("#password")).to_be_visible()
            await expect(card.locator(".logo.big")).to_be_hidden()
            await card.locator(".corner").click()
            await expect(card.locator(".logo.big")).to_be_visible()
            await card.locator(".corner").click()
            await page.fill("#name", "admin")
            await page.fill("#password", served.password)
            await page.click("button[type=submit]")
            await page.wait_for_url(re.compile(r"/stall$"))
        finally:
            await browser.close()


async def test_the_appearance_part_dresses_the_whole_window():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN", color_scheme="dark")
            page = await signed_in(await context.new_page(), served)
            await expect(page.locator("html")).to_have_attribute("data-theme", "night")
            await page.goto(f"{served.url}/settings/appearance")
            part = page.frame_locator("iframe.frame").frame_locator("iframe.pane")
            await part.locator("label:has(input[name=theme][value=light])").click()
            await expect(page.locator("html")).to_have_attribute("data-theme", "day")
            part = page.frame_locator("iframe.frame").frame_locator("iframe.pane")
            await part.locator("label:has(input[name=day_theme][value=night])").click()
            await expect(page.locator("html")).to_have_attribute("data-theme", "night")
            # the language list opens over the frames, drawn by the page
            part = page.frame_locator("iframe.frame").frame_locator("iframe.pane")
            await part.locator(".input.select").click()
            await page.locator(".choosing .choice", has_text="English").click()
            await expect(page.locator("html")).to_have_attribute("lang", "en")
            await expect(page.locator(".side .nav-group").first).to_have_text(
                "Workbench"
            )
            # the card beside the account turns to the night at a click, its
            # buttons hinting what they do
            await page.locator(".me .theme button[value=dark]").hover()
            await expect(page.locator(".tooltip")).to_have_text("Always night")
            await page.locator(".me .theme button[value=dark]").click()
            await expect(page.locator("html")).to_have_attribute("data-theme", "night")
            # kept for the account, not the window
            other = await (
                await browser.new_context(
                    storage_state=await context.storage_state(), color_scheme="dark"
                )
            ).new_page()
            await other.goto(f"{served.url}/stall")
            await expect(other.locator("html")).to_have_attribute("lang", "en")
            await expect(other.locator("html")).to_have_attribute("data-theme", "night")
        finally:
            await browser.close()


async def test_a_field_left_empty_says_so_under_itself():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN", color_scheme="dark")
            page = await signed_in(await context.new_page(), served)
            await page.goto(f"{served.url}/settings/roles")
            part = page.frame_locator("iframe.frame").frame_locator("iframe.pane")
            await part.locator("a[href='/ui/access/roles/new']").click()
            await part.locator("button[type=submit]").click()
            name = part.locator("#name")
            await expect(name).to_have_attribute("aria-invalid", "true")
            await expect(part.locator(".problem")).to_have_text("请填写这一项")
            await name.fill("运营")
            await expect(part.locator(".problem")).to_have_count(0)
        finally:
            await browser.close()


async def test_the_window_follows_its_topics_in_one_request_a_round():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context()
            page = await signed_in(await context.new_page(), served)
            asked: list[object] = []
            page.on(
                "request",
                lambda request: (
                    asked.append(request.post_data_json)
                    if request.url.endswith("/api/server/poll")
                    else None
                ),
            )
            badge = page.locator('.side .nav[href="/stall"] .tally')
            await expect(badge).to_have_text("1")
            panel = page.frame_locator(".side iframe.panel")
            await expect(panel.locator("#counted")).to_have_text("counted 1")
            await page.request.post(f"{served.url}/ui/stall/bump")
            await expect(badge).to_have_text("2")
            await expect(panel.locator("#counted")).to_have_text("counted 2")
            # the sidebar's badge and the panel inside its frame went in the same requests
            assert any(
                isinstance(body, dict) and len(body["subscriptions"]) >= 2
                for body in asked
            )
        finally:
            await browser.close()


async def test_a_page_on_its_own_follows_its_topics():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context()
            page = await signed_in(await context.new_page(), served)
            await page.goto(f"{served.url}/ui/stall/panel")
            counted = page.locator("#counted")
            await expect(counted).to_have_text(re.compile(r"^counted \d+$"))
            before = int((await counted.text_content() or "").split()[-1])
            await page.request.post(f"{served.url}/ui/stall/bump")
            await expect(counted).to_have_text(f"counted {before + 1}")
        finally:
            await browser.close()


async def test_a_piece_htmx_swaps_in_follows_its_topic():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context()
            page = await signed_in(await context.new_page(), served)
            frame = page.frame_locator("iframe.frame")
            await frame.locator("#more").click()
            piece = frame.locator("#piece")
            await expect(piece).to_have_text(re.compile(r"^\d+$"))
            before = int(await piece.text_content() or "")
            await page.request.post(f"{served.url}/ui/stall/bump")
            await expect(piece).to_have_text(str(before + 1))
        finally:
            await browser.close()


async def test_an_element_that_left_its_page_is_no_longer_followed():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context()
            page = await signed_in(await context.new_page(), served)
            shelf = page.frame_locator("iframe.frame").locator("#shelf")
            await expect(shelf).to_have_text("a")
            await shelf.evaluate("element => element.remove()")
            asked: list[str] = []
            page.on(
                "request",
                lambda request: (
                    asked.append(request.post_data or "")
                    if request.url.endswith("/api/server/poll")
                    else None
                ),
            )
            # the sidebar's badge goes on asking, round after round
            for _ in range(100):
                if len(asked) >= 3:
                    break
                await asyncio.sleep(0.1)
            assert "stall.shelf" not in asked[-1]
        finally:
            await browser.close()


async def test_a_panel_sits_above_the_bottom_bar_on_a_phone():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(viewport={"width": 390, "height": 844})
            page = await signed_in(await context.new_page(), served)
            await expect(page.locator(".strip iframe.panel")).to_be_visible()
            await expect(page.locator(".side iframe.panel")).to_be_hidden()
            strip = page.frame_locator(".strip iframe.panel")
            await expect(strip.locator("#counted")).to_have_text("counted 1")
        finally:
            await browser.close()


async def test_a_share_page_in_a_frame_says_when_it_is_done():
    async with serving() as served, async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="en-US")
            page = await signed_in(await context.new_page(), served)
            await page.request.post(
                f"{served.url}/ui/access/roles/",
                form={"name": "ops", "permissions": "stands.view"},
            )
            made = await page.request.post(
                f"{served.url}/ui/stand/", form={"name": "north"}
            )
            await page.goto(
                f"{served.url}/ui/stand/{(await made.json())['ref']}/sharing"
            )
            share = page.frame_locator("#share")
            await share.locator("input[name=grant]").first.check()
            await expect(share.locator(".dirty")).to_be_visible()
            await share.locator("footer button[type=submit]").click()
            await expect(page.locator("body")).to_have_attribute("data-done", "yes")
            # what was saved is there when the page opens again, and giving up
            # is done as well
            await page.reload()
            await expect(share.locator("input[name=grant]").first).to_be_checked()
            await share.locator("footer button[type=button]").click()
            await expect(page.locator("body")).to_have_attribute("data-done", "yes")
            # on a phone, each point is a toggle carrying its name
            await page.set_viewport_size({"width": 390, "height": 844})
            await expect(share.locator(".ck span").first).to_be_visible()
        finally:
            await browser.close()


async def test_sharing_many_permissions_fits_a_drawer_and_keeps_its_grants():
    async with (
        serving() as served,
        async_playwright() as driver,
        served.access.points(
            "stand", ("stands.rename", "stands.inspect", "stands.manage")
        ),
    ):
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800}, locale="en-US"
            )
            page = await signed_in(await context.new_page(), served)
            for name in ("Team members", "Administrators"):
                await page.request.post(
                    f"{served.url}/ui/access/roles/", form={"name": name}
                )
            made = await page.request.post(
                f"{served.url}/ui/stand/", form={"name": "Build computer"}
            )
            await page.goto(
                f"{served.url}/ui/stand/{(await made.json())['ref']}/sharing"
            )
            await page.locator("#share").evaluate(
                "frame => { frame.style.width = '360px'; frame.style.height = '600px'; }"
            )
            share = page.frame_locator("#share")
            await expect(share.locator(".gr")).to_have_count(2)
            team = share.locator('.gr[data-name="team members"]')
            await team.locator("summary").click()
            await expect(team.locator(".ck")).to_have_count(6)
            await team.locator("input[name=grant]").first.check()
            await expect(team.locator(".count")).to_have_text("1 / 6")
            assert await share.locator("html").evaluate(
                "el => el.scrollWidth <= el.clientWidth"
            )
            await share.locator("footer button[type=submit]").click()
            await expect(page.locator("body")).to_have_attribute("data-done", "yes")
            await page.reload()
            share = page.frame_locator("#share")
            team = share.locator('.gr[data-name="team members"]')
            await team.locator("summary").click()
            await expect(team.locator("input[name=grant]").first).to_be_checked()
            await share.locator("input[type=search]").fill("Team")
            await expect(share.locator(".gr:visible")).to_have_count(1)
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await share.locator("html").evaluate(
                "el => el.scrollWidth <= el.clientWidth"
            )
        finally:
            await browser.close()
