import os
import json
import re
import traceback
import asyncio
import random
from pathlib import Path
import aiohttp

def natural_keys(text):
    return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]

def clean_desc_html(desc_html):
    desc_html = re.sub(r'<div class="ProductDetail-title[^>]*>.*?<\/div>', '', desc_html, flags=re.DOTALL)
    return desc_html.lstrip()

def has_desc_img_spans(desc_html):
    return bool(re.search(r'<span\s+id=["\']desc-img-\d+["\']', desc_html, re.IGNORECASE))

async def is_cloudflare_challenge(page):
    try:
        if await page.locator('iframe[title*="驗證"], iframe[title*="verify"], iframe[title*="captcha"]').count() > 0:
            return True
        if await page.locator('div:has-text("請勾選核取方塊")').count() > 0:
            return True
        if await page.locator('form.challenge-form, #cf-verify-form, .cf-challenge').count() > 0:
            return True
        t = await page.title()
        if t.lower().find("attention required") >= 0 or t.lower().find("cloudflare") >= 0 or t.lower().find("just a moment") >= 0:
            return True
    except Exception:
        pass
    return False

async def try_solve_cf_challenge(page, log_func):
    try:
        frames = page.frames
        found = False
        for frame in frames:
            try:
                checkbox = await frame.query_selector('input[type="checkbox"]')
                if checkbox:
                    log_func(5, "發現Cloudflare人機驗證核取方塊，嘗試點擊")
                    box = await checkbox.bounding_box()
                    if box:
                        x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
                        await page.mouse.move(x, y)
                        await asyncio.sleep(0.3)
                    await checkbox.click(force=True)
                    await page.wait_for_timeout(2200)
                    found = True
                    break
            except Exception:
                continue
        if found:
            return True
        for frame in frames:
            try:
                checkbox = await frame.query_selector('input[type="checkbox"]')
                if checkbox:
                    await checkbox.focus()
                    await page.keyboard.press('Enter')
                    await page.wait_for_timeout(2000)
                    log_func(5, "已嘗試Enter")
                    return True
            except Exception:
                continue
        for frame in frames:
            try:
                await frame.eval_on_selector('input[type="checkbox"]', 'el => {el.checked=true;el.dispatchEvent(new Event("change", {bubbles:true}))}')
                log_func(5, "已嘗試JS設置checkbox")
                await page.wait_for_timeout(2000)
                return True
            except Exception:
                continue
        log_func(5, "找不到Cloudflare核取方塊iframe")
        return False
    except Exception as e:
        log_func(100, f"點擊Cloudflare核取方塊出錯: {e}\n{traceback.format_exc()}")
    return False

async def head_check_product_url(slug, domain, log_func=None):
    if log_func is None:
        log_func = lambda percent, msg: print(f"PROGRESS:{percent}:{msg}", flush=True)
    domain = domain.rstrip('/')
    product_url = f"{domain}/item/{slug}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(product_url, timeout=10, allow_redirects=True) as resp:
                if resp.status == 200:
                    log_func(101, f"前台 HEAD 檢查：商品頁面 {product_url} 已存在 (HTTP 200)")
                    return True, resp.status
                else:
                    log_func(100, f"前台 HEAD 檢查：商品頁面 {product_url} 不存在，狀態碼: {resp.status}")
                    return False, resp.status
    except Exception as e:
        log_func(100, f"前台 HEAD 檢查異常: {e}")
        return False, "EXCEPTION"

async def upload_single_product_async(
    context, info_path, output_path, pname, signal_func, domain="https://gd.bvshop.tw", speed_params=None
):
    def log_func(percent, msg):
        signal_func.emit(pname, percent, None, None, msg)

    # 預設值保護
    if speed_params is None:
        speed_params = dict(delay=(0.08, 0.15), mouse_steps=2, scroll_times=1)

    async def human_delay():
        await asyncio.sleep(random.uniform(*speed_params['delay']))

    async def random_mouse_move(page, steps=None):
        if steps is None:
            steps = speed_params['mouse_steps']
        if steps == 0:
            return
        width = await page.evaluate("window.innerWidth")
        height = await page.evaluate("window.innerHeight")
        for _ in range(steps):
            x = random.randint(0, width-10)
            y = random.randint(0, height-10)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.01, 0.05))

    async def random_scroll(page, times=None):
        if times is None:
            times = speed_params['scroll_times']
        for _ in range(times):
            scroll_y = random.randint(100, 700)
            await page.evaluate(f"window.scrollBy(0, {scroll_y});")
            await asyncio.sleep(random.uniform(0.05, 0.15))

    try:
        with open(info_path, encoding="utf-8") as f:
            info = json.load(f)
        with open(output_path, encoding="utf-8") as f:
            output = json.load(f)
    except Exception as e:
        signal_func.emit(pname, 100, False, 0, f"讀取商品資訊檔失敗: {e}\n{traceback.format_exc()}")
        return False, "讀取商品資訊檔失敗", False

    main_images = output.get("main_images_local", [])
    desc_images = output.get("desc_images_local", [])
    not_exist_files = [f for f in main_images if not os.path.exists(f)]
    not_exist_desc = [f for f in desc_images if not os.path.exists(f)]
    if not_exist_files:
        signal_func.emit(pname, 100, False, 0, f"❌ 主圖檔案不存在: {not_exist_files}")
        return False, "主圖檔案不存在", False
    if not_exist_desc:
        signal_func.emit(pname, 100, False, 0, f"❌ 描述圖檔案不存在: {not_exist_desc}")
        return False, "描述圖檔案不存在", False

    main_images = sorted(main_images, key=lambda x: natural_keys(Path(x).name))
    desc_images = sorted(desc_images, key=lambda x: natural_keys(Path(x).name))
    name = info.get("商品名稱", "")
    subtitle = info.get("商品副標題", "")
    summary_html = info.get("商品摘要HTML", "")
    desc_html = info.get("商品描述HTML", "") or info.get("商品描述_繁體中文_HTML", "")
    desc_html = clean_desc_html(desc_html)
    seo_title = info.get("SEO標題", "")
    seo_description = info.get("SEO描述", "")
    seo_keywords = info.get("SEO關鍵字", "")
    slug = info.get("商品網址SLUG") or output.get("product_slug", "")

    CREATE_URL = "https://bvshop-manage.bvshop.tw/product/create?type=1"
    browser_timeout = 5

    page = await context.new_page()
    cf_encountered = False
    try:
        # ==== 人類行為: 一進頁面隨機滑鼠與滾動 ====
        await human_delay()
        await random_mouse_move(page)
        await random_scroll(page)
        await human_delay()

        # ==== robust goto with retry, domcontentloaded ====
        goto_retries = 3
        for goto_try in range(goto_retries):
            try:
                await page.goto(CREATE_URL, timeout=60000, wait_until='domcontentloaded')
                break
            except Exception as e:
                await page.screenshot(path=f"debug_goto_fail_{goto_try}.png")
                log_func(100, f"[goto重試] 進入建立頁失敗第{goto_try+1}次: {e}")
                if goto_try == goto_retries-1:
                    await page.close()
                    return False, f"進入建立頁超時: {e}", cf_encountered
                await asyncio.sleep(4)
        page_title = await page.title()
        log_func(8, f"載入頁面完成，現頁title: {page_title} url: {page.url}")

        # Cloudflare防火牆直接退出
        if "cloudflare" in page_title.lower() or "just a moment" in page_title.lower():
            await page.screenshot(path="debug_cf_block.png")
            log_func(100, f"⚠️ 偵測到 Cloudflare 防火牆驗證頁，流程退出。")
            await page.close()
            return False, "Cloudflare 防火牆驗證頁，流程退出", True

        cf_try = 0
        while await is_cloudflare_challenge(page):
            cf_encountered = True
            if cf_try > 5:
                msg = "RETRY:Cloudflare 驗證多次仍卡住，暫時性錯誤"
                log_func(100, msg)
                await page.screenshot(path=f"cf_challenge_{cf_try}.png")
                await page.close()
                return False, msg, cf_encountered
            log_func(3, f"偵測到 Cloudflare 人機驗證頁面，進行破解第{cf_try+1}次")
            await try_solve_cf_challenge(page, log_func)
            cf_try += 1
            await page.wait_for_timeout(2000 * cf_try)
            await page.reload()
            await page.wait_for_timeout(2000 * cf_try)
            if not await is_cloudflare_challenge(page):
                break

        # === 等主圖上傳按鈕 ===
        log_func(10, "等待主圖上傳... (檢查 .basic-upload 是否存在)")
        await human_delay()
        await random_mouse_move(page)
        upload_wait_retry = 2
        for try_idx in range(upload_wait_retry):
            try:
                await page.wait_for_selector('.basic-upload', timeout=15000)
                async with page.expect_file_chooser() as fc_info:
                    await page.click('.basic-upload')
                file_chooser = await fc_info.value
                break
            except Exception as e:
                await page.screenshot(path=f"debug_basic_upload_not_found_{try_idx}.png")
                btn_classes = await page.eval_on_selector_all('button', 'els => els.map(e => e.className)')
                log_func(100, f"找不到 .basic-upload，第{try_idx+1}次重試，button class: {btn_classes}")
                await asyncio.sleep(2)
        else:
            msg = "主圖上傳按鈕(.basic-upload)找不到，請檢查 debug_basic_upload_not_found_*.png"
            log_func(100, msg)
            await page.close()
            return False, msg, cf_encountered

        if main_images:
            await file_chooser.set_files(main_images)
            log_func(12, f"已上傳主圖 {len(main_images)} 張：{main_images}")
            elapsed = 0
            interval = 300
            timeout = 18000
            while elapsed < timeout:
                img_count = await page.evaluate("() => document.querySelectorAll('#product-images-area img').length")
                log_func(13, f"等待主圖縮圖顯示({img_count}/{len(main_images)})")
                if img_count == len(main_images):
                    log_func(14, f"所有主圖縮圖顯示完成")
                    break
                await page.wait_for_timeout(interval)
                elapsed += interval
            else:
                msg = "RETRY:主圖縮圖未全部出現，流程中止，暫時性錯誤"
                log_func(100, msg)
                await page.close()
                return False, msg, cf_encountered
        else:
            log_func(12, "⚠️ 沒有主圖可以上傳")

        await human_delay()
        await random_mouse_move(page)

        await page.wait_for_selector('input[placeholder="商品名稱是？"]', timeout=browser_timeout*1000)
        await page.fill('input[placeholder="商品名稱是？"]', name)
        log_func(22, f"商品名稱已自動填入：{name}")

        await human_delay()
        subtitle_xpath = '//div[@class="basic-item"][div/label[normalize-space()="商品副標題"]]/div/textarea'
        await page.wait_for_selector(subtitle_xpath, timeout=browser_timeout*1000)
        await page.fill(subtitle_xpath, subtitle)
        log_func(25, f"已自動填入商品副標題：{subtitle}")

        await human_delay()
        summary_xpath = '//div[@class="basic-item"][div/label[normalize-space()="商品摘要"]]/div/textarea'
        await page.wait_for_selector(summary_xpath, timeout=browser_timeout*1000)
        if summary_html:
            await page.fill(summary_xpath, summary_html)
            log_func(28, "以 HTML 模式填入商品摘要")
        else:
            await page.fill(summary_xpath, "")
            log_func(28, "已自動填入商品摘要（空）")

        await human_delay()
        await page.wait_for_selector('input[placeholder="自訂義商品網址"]', timeout=browser_timeout*1000)
        await page.fill('input[placeholder="自訂義商品網址"]', slug)
        log_func(30, f"已自動填入商品網址 SLUG：{slug}")

        await human_delay()
        await page.wait_for_selector('input[placeholder="SEO-Title"]', timeout=browser_timeout*1000)
        await page.fill('input[placeholder="SEO-Title"]', seo_title)
        await page.wait_for_selector('textarea[placeholder="SEO-Description"]', timeout=browser_timeout*1000)
        await page.fill('textarea[placeholder="SEO-Description"]', seo_description)
        await page.wait_for_selector('textarea[placeholder="SEO-Keywords"]', timeout=browser_timeout*1000)
        await page.fill('textarea[placeholder="SEO-Keywords"]', seo_keywords)
        log_func(33, f"已自動填入SEO資料")

        await human_delay()
        await page.click('#product_size-tab')
        log_func(34, "已切換到商品規格頁籤")
        await human_delay()
        await random_scroll(page)

        spec_types = info.get("規格類型", [])
        spec_names = info.get("各規格名稱", [])
        spec_combos = info.get("規格組合明細", [])
        is_single_spec = not spec_types or len(spec_types) == 0

        if is_single_spec:
            await page.click('label[for="singleRadio"]')
            log_func(35, "已選擇單一規格")
            await human_delay()
            await page.wait_for_selector('input[validate-name="price"]', timeout=browser_timeout*1000)
            price_val = info.get("單規格價格", "")
            special_price_val = info.get("單規格特價", "")
            await page.fill('input[validate-name="price"]', str(price_val) if price_val else "")
            log_func(36, f"已自動填入售價: {price_val}")
            await page.fill('input[validate-name="special_price"]', str(special_price_val) if special_price_val else "")
            log_func(37, f"已自動填入特價: {special_price_val}")
            cost_val = info.get("成本", "")
            if cost_val:
                await page.fill('input[validate-name="cost"]', str(cost_val))
                log_func(38, f"已自動填入成本: {cost_val}")
            await page.wait_for_selector('input[validate-name="quantity"]', timeout=browser_timeout*1000)
            quantity = info.get("庫存", None)
            if quantity is None or quantity == "":
                quantity = 0
                log_func(39, "無庫存資料，自動填 0")
            await page.fill('input[validate-name="quantity"]', str(quantity))
            log_func(40, f"已自動填入庫存: {quantity}")
            try:
                await page.wait_for_selector('input[validate-name="sku"]', timeout=browser_timeout*1000)
                sku_val = info.get("商品型號", info.get("貨號", ""))
                barcode_val = info.get("條碼", "")
                await page.fill('input[validate-name="sku"]', str(sku_val))
                log_func(41, f"已自動填入貨號: {sku_val}")
                await page.fill('input[validate-name="barcode"]', str(barcode_val))
                log_func(42, f"已自動填入條碼: {barcode_val}")
            except Exception as e:
                log_func(42, f"填入貨號或條碼時發生錯誤: {e}")
            await page.click('#product_des-tab')
            log_func(43, "已切換到商品描述頁籤")
        else:
            await page.click('label[for="multipleRadio"]')
            log_func(35, "已選擇多規格")
            await page.wait_for_selector('input[validate-name="options"]', timeout=browser_timeout*1000)
            for i in range(len(spec_types) - 1):
                await page.locator('button', has_text="新增規格").first.click()
                log_func(37, f"點擊第 {i+1} 次新增規格")
                await page.wait_for_timeout(500)
            for idx, (stype, snames) in enumerate(zip(spec_types, spec_names)):
                all_type_inputs = await page.query_selector_all('input[validate-name="options"]')
                if idx < len(all_type_inputs):
                    await all_type_inputs[idx].fill(stype)
                    log_func(38, f"已填入第{idx+1}組規格類型：{stype}")
                else:
                    log_func(38, f"找不到第{idx+1}組規格類型 input")
                name_inputs = await page.query_selector_all(f'.no_{idx} .bootstrap-tagsinput input')
                if name_inputs:
                    name_input = name_inputs[0]
                    for sname in snames:
                        await name_input.fill(sname)
                        await name_input.press("Enter")
                        log_func(39, f"已填入第{idx+1}組規格名稱：{sname}")
                        await page.wait_for_timeout(150)
                else:
                    log_func(39, f"找不到第{idx+1}組規格名稱 input")
            await page.wait_for_selector('.product-format', timeout=browser_timeout*1000)
            formats = await page.query_selector_all('.product-format')
            log_func(40, f"偵測到 {len(formats)} 組規格欄位")
            for idx, combo in enumerate(spec_combos):
                pf = formats[idx] if idx < len(formats) else None
                if not pf:
                    log_func(41, f"找不到第{idx+1}組 product-format 區塊")
                    continue
                v = combo.get("價格")
                if v is not None and v != "":
                    price_input = await pf.query_selector('input[validate-name^="price_"]')
                    if price_input:
                        await price_input.fill(str(v))
                    log_func(42, f"組合{idx+1} 售價: {v}")
                v = combo.get("特價")
                if v is not None and v != "":
                    special_input = await pf.query_selector('input[validate-name^="special_price_"]')
                    if special_input:
                        await special_input.fill(str(v))
                    log_func(43, f"組合{idx+1} 特價: {v}")
                v = combo.get("條碼")
                if v is not None and v != "":
                    barcode_input = await pf.query_selector('input[validate-name^="barcode_"]')
                    if barcode_input:
                        await barcode_input.fill(str(v))
                    log_func(44, f"組合{idx+1} 條碼: {v}")
                v = combo.get("商品型號")
                if v is not None and v != "":
                    sku_input = await pf.query_selector('input[validate-name^="sku_"]')
                    if sku_input:
                        await sku_input.fill(str(v))
                    log_func(45, f"組合{idx+1} 型號: {v}")
                v = combo.get("庫存")
                if v is not None and v != "":
                    quantity_input = await pf.query_selector('input[validate-name^="quantity_"]')
                    if quantity_input:
                        await quantity_input.fill(str(v))
                    log_func(46, f"組合{idx+1} 庫存: {v}")
            await page.click('#product_des-tab')
            log_func(47, "已切換到商品描述頁籤")

        await human_delay()
        await random_mouse_move(page)
        await random_scroll(page)

        # === 商品描述 HTML ===
        desc_iframe_selector = 'iframe#description_ifr'
        max_wait = 10
        t0 = asyncio.get_event_loop().time()
        while True:
            try:
                await page.wait_for_selector(desc_iframe_selector, timeout=1000, state='visible')
                break
            except Exception:
                if asyncio.get_event_loop().time() - t0 > max_wait:
                    msg = f"RETRY:TinyMCE 編輯器初始化暫時性失敗：等待元素 {desc_iframe_selector} 超過 {max_wait} 秒，可能卡死/hidden"
                    log_func(100, msg)
                    await page.close()
                    return False, msg, cf_encountered
        frame = page.frame(name="description_ifr")
        await frame.wait_for_selector('body', timeout=1500)
        try:
            await frame.evaluate(f'body => body.innerHTML = {json.dumps(desc_html)}', await frame.query_selector('body'))
        except Exception as e:
            msg = f"RETRY:TinyMCE 編輯器初始化暫時性失敗：{e}\n{traceback.format_exc()}"
            log_func(100, msg)
            await page.close()
            return False, msg, cf_encountered
        log_func(50, f"商品描述HTML已填入")

        await human_delay()
        await random_mouse_move(page)

        # === 商品描述插圖 ===
        try:
            if has_desc_img_spans(desc_html):
                for idx, img_path in enumerate(desc_images):
                    span_id = f"desc-img-{idx+1}"
                    log_func(70, f"插入描述圖 {idx+1}/{len(desc_images)}，錨點:{span_id}")
                    await frame.evaluate(f'''
                        body => {{
                            var span = body.querySelector("span#{span_id}");
                            if(span) {{
                                var range = document.createRange();
                                range.selectNode(span);
                                var sel = window.getSelection();
                                sel.removeAllRanges();
                                sel.addRange(range);
                            }}
                        }}
                    ''', await frame.query_selector('body'))
                    await page.wait_for_timeout(50)
                    async with page.expect_file_chooser() as fc_info:
                        await page.locator('button[aria-label="插入/編輯圖片"],button[title="插入/編輯圖片"]').first.click()
                        await page.locator('button.tox-browse-url[title="圖片網址"]').click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(str(Path(img_path)))
                    await page.wait_for_timeout(400)
                    await page.locator('div.tox-dialog button.tox-button:has-text("儲存")').click()
                    await frame.evaluate(f'''
                        body => {{
                            var span = body.querySelector("span#{span_id}");
                            if(span) span.remove();
                        }}
                    ''', await frame.query_selector('body'))
                    await page.wait_for_timeout(80)
                    log_func(73, f"已插入描述圖 {img_path} 於 {span_id}")
            else:
                for idx, img_path in enumerate(desc_images):
                    log_func(70, f"文末插入描述圖 {idx+1}/{len(desc_images)}：{img_path}")
                    await frame.focus('body')
                    await frame.evaluate('body => { var range = document.createRange(); range.selectNodeContents(body); range.collapse(false); var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range); }', await frame.query_selector('body'))
                    await page.wait_for_timeout(50)
                    insert_ok = False
                    for attempt in range(2):  # 最多兩次
                        try:
                            async with page.expect_file_chooser() as fc_info:
                                await page.locator('button[aria-label="插入/編輯圖片"],button[title="插入/編輯圖片"]').first.click()
                                await page.locator('button.tox-browse-url[title="圖片網址"]').click()
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(str(Path(img_path)))
                            await page.wait_for_timeout(400)
                            await page.locator('div.tox-dialog button.tox-button:has-text("儲存")').click()
                            await page.wait_for_timeout(150)
                            insert_ok = True
                            log_func(73, f"描述圖 {img_path} 已插入文末")
                            break
                        except Exception as e:
                            log_func(100, f"插入描述圖 {img_path} 第{attempt+1}次失敗: {e}")
                            await page.screenshot(path=f"desc_img_fail_{idx+1}_try{attempt+1}.png")
                            await page.wait_for_timeout(1000)
                    if not insert_ok:
                        raise RuntimeError(f"描述圖 {img_path} 插入失敗")
                    try:
                        await page.wait_for_selector('.tox-dialog', state='detached', timeout=5000)
                    except Exception:
                        pass
            log_func(80, "所有描述圖已插入正確位置")
        except Exception as e:
            msg = f"FATAL:描述圖片插入失敗：{e}\n{traceback.format_exc()}"
            log_func(100, msg)
            await page.close()
            return False, msg, cf_encountered

        await human_delay()
        await random_mouse_move(page)

        # === 儲存 ===
        already_saved = False
        try:
            save_btn_xpath = '//div[contains(@class,"all-btn") and contains(@class,"save-btn")]/button'
            await page.wait_for_selector(save_btn_xpath, timeout=browser_timeout*1000)
            await human_delay()
            await random_mouse_move(page)
            if not already_saved:
                await page.click(save_btn_xpath)
                already_saved = True
                log_func(100, "✅ 已自動點擊儲存，等待頁面跳轉判斷是否成功...")
                try:
                    await page.wait_for_url("https://bvshop-manage.bvshop.tw/product*", timeout=20000)
                    log_func(100, "✅ 儲存成功，已自動跳轉回商品列表頁！")
                    await page.close()
                    return True, "上架成功", cf_encountered
                except Exception:
                    error_msgs = []
                    selectors = [
                        '.el-message', '.el-alert', '.alert', '.ant-message', '.ant-alert',
                        'div:has-text("錯誤")', 'div:has-text("失敗")', 'div:has-text("請填寫")',
                        '.el-form-item__error', '.invalid-feedback', 'span.error'
                    ]
                    for sel in selectors:
                        try:
                            els = await page.query_selector_all(sel)
                            for el in els:
                                txt = await el.inner_text()
                                if txt and txt.strip():
                                    error_msgs.append(f"[{sel}] {txt.strip()}")
                        except Exception:
                            continue
                    await page.screenshot(path="debug_save_fail.png")
                    await page.screenshot(path="debug_save_full.png", full_page=True)
                    log_func(100, f"❌ 未跳轉回商品列表頁，發現錯誤訊息: {error_msgs}")
                    await page.close()
                    return False, f"商品儲存失敗, 詳細錯誤請見 debug_save_fail.png, error_msgs: {error_msgs}", cf_encountered
        except Exception as e:
            msg = f"FATAL:儲存商品資料失敗: {e}\n{traceback.format_exc()}"
            log_func(100, msg)
            await page.close()
            return False, msg, cf_encountered

    except Exception as e:
        msg = f"FATAL:本輪異常: {e}\n{traceback.format_exc()}"
        log_func(100, msg)
        try:
            await page.close()
        except Exception:
            pass
        return False, msg, cf_encountered
