import os
import json
import asyncio
from PyQt5.QtCore import QObject, pyqtSignal
from playwright.async_api import async_playwright
from up_single import upload_single_product_async, head_check_product_url
from speed_controller import SpeedController, BehaviorMode

class BVShopBatchUploader(QObject):
    product_progress_signal = pyqtSignal(str, int, object, object, str)
    all_done_signal = pyqtSignal(int, int, int, list)

    def __init__(
        self, src_dir, username, password, max_workers=3,
        product_domain="https://gd.bvshop.tw", headless=True, only_failed=None,
        behavior_mode=BehaviorMode.AUTO,
        speed_status_callback=None,
        round_status_callback=None
    ):
        super().__init__()
        self.src_dir = src_dir
        self.username = username
        self.password = password
        self.max_workers = max_workers
        self.product_domain = product_domain
        self.headless = headless
        self.only_failed = only_failed
        self.behavior_mode = behavior_mode
        self.speed_status_callback = speed_status_callback
        self.round_status_callback = round_status_callback
        self._should_stop = False
        self._should_pause = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()

    def is_product_dir(self, pdir):
        return (
            os.path.isdir(pdir) and
            os.path.exists(os.path.join(pdir, "product_info.json")) and
            os.path.exists(os.path.join(pdir, "product_output.json"))
        )

    def find_product_dirs(self, src_dir):
        if self.only_failed:
            product_dirs = []
            for name in self.only_failed:
                pdir = os.path.join(src_dir, name)
                if self.is_product_dir(pdir):
                    product_dirs.append(pdir)
            return product_dirs
        if self.is_product_dir(src_dir):
            return [src_dir]
        product_dirs = []
        for name in os.listdir(src_dir):
            pdir = os.path.join(src_dir, name)
            if self.is_product_dir(pdir):
                product_dirs.append(pdir)
        return product_dirs

    def check_product_files(self, pdir):
        info_path = os.path.join(pdir, "product_info.json")
        output_path = os.path.join(pdir, "product_output.json")
        try:
            with open(info_path, encoding="utf-8") as f:
                info = json.load(f)
        except Exception as e:
            return False, f"商品資料(product_info.json)壞掉: {e}"
        try:
            with open(output_path, encoding="utf-8") as f:
                output = json.load(f)
        except Exception as e:
            return False, f"商品資料(product_output.json)壞掉: {e}"
        main_images = output.get("main_images_local", [])
        not_exist_files = [f for f in main_images if not os.path.exists(f)]
        if not_exist_files:
            return False, f"主圖檔案不存在: {not_exist_files}"
        desc_images = output.get("desc_images_local", [])
        not_exist_desc_files = [f for f in desc_images if not os.path.exists(f)]
        if not_exist_desc_files:
            return False, f"描述圖檔案不存在: {not_exist_desc_files}"
        return True, ""

    def get_slug(self, pdir):
        try:
            info_path = os.path.join(pdir, "product_info.json")
            output_path = os.path.join(pdir, "product_output.json")
            slug = ""
            if os.path.exists(info_path):
                with open(info_path, encoding="utf-8") as f:
                    info = json.load(f)
                slug = info.get("商品網址SLUG", "")
            if not slug and os.path.exists(output_path):
                with open(output_path, encoding="utf-8") as f:
                    output = json.load(f)
                slug = output.get("product_slug", "")
            return slug
        except Exception:
            return ""

    def stop(self):
        self._should_stop = True

    def pause(self):
        self._should_pause = True
        self._pause_event.clear()

    def resume(self):
        self._should_pause = False
        self._pause_event.set()

    def batch_upload(self):
        asyncio.run(self.batch_upload_async())

    async def batch_upload_async(self):
        MAX_RETRIES = 5
        product_dirs = self.find_product_dirs(self.src_dir)
        pname_to_pdir = {os.path.basename(pdir): pdir for pdir in product_dirs}
        all_names = set(pname_to_pdir.keys())
        retries = 0
        all_success = set()
        all_fail = set(all_names)
        fail_list_accumulate = []
        speed_controller = SpeedController(mode=self.behavior_mode)
        # 通知初始輪數
        if self.round_status_callback is not None:
            self.round_status_callback(1, MAX_RETRIES)

        while retries < MAX_RETRIES and all_fail:
            if self.round_status_callback is not None:
                self.round_status_callback(retries+1, MAX_RETRIES)

            fail_this_round = []
            success_this_round = []
            checked_product_dirs = []

            # 1. 檢查檔案齊全
            for pname in all_fail:
                pdir = pname_to_pdir[pname]
                ok, errmsg = self.check_product_files(pdir)
                if not ok:
                    self.product_progress_signal.emit(pname, 100, False, 0, errmsg)
                    fail_this_round.append((pname, errmsg))
                else:
                    checked_product_dirs.append(pdir)

            # 2. Playwright流程（登入只跑一次）
            if checked_product_dirs:
                sem = asyncio.Semaphore(self.max_workers)
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=self.headless)
                    context = await browser.new_context()
                    page_login = await context.new_page()
                    await page_login.goto("https://bvshop-manage.bvshop.tw/login", timeout=30000)
                    await page_login.wait_for_selector('input[name="email"]', timeout=15000)
                    await page_login.fill('input[name="email"]', self.username)
                    await page_login.wait_for_selector('input[type="password"]', timeout=5000)
                    try:
                        await page_login.fill('input[type="password"].el-input__inner', self.password)
                    except Exception:
                        await page_login.fill('input[type="password"]', self.password)
                    await page_login.click('button[type="submit"]')
                    await page_login.wait_for_selector('header.main-header', timeout=15000)
                    await page_login.close()

                    tasks = []
                    for pdir in checked_product_dirs:
                        pname = os.path.basename(pdir)
                        info_path = os.path.join(pdir, "product_info.json")
                        output_path = os.path.join(pdir, "product_output.json")
                        speed_params = speed_controller.get_params()
                        tasks.append(
                            self._upload_one_product(sem, context, pname, info_path, output_path, self.product_domain, speed_params)
                        )
                    results = await asyncio.gather(*tasks)
                    for pname, ok, msg, cf_encountered in results:
                        speed_controller.update(cf_encountered)
                        if self.speed_status_callback is not None:
                            # 及時通知目前速度模式
                            this_mode = (
                                "極速" if speed_controller.current == BehaviorMode.SPEED
                                else "安全" if speed_controller.current == BehaviorMode.SAFE
                                else "自動"
                            )
                            self.speed_status_callback(this_mode)
                        if ok:
                            success_this_round.append(pname)
                        else:
                            fail_this_round.append((pname, msg))
                    await context.close()
                    await browser.close()

            # 3. 檢查失敗商品的 head
            still_fail = []
            for pname, errmsg in fail_this_round:
                pdir = pname_to_pdir.get(pname)
                slug = self.get_slug(pdir) if pdir else ""
                if slug:
                    ok, status = await head_check_product_url(slug, self.product_domain)
                    if ok:
                        self.product_progress_signal.emit(pname, 100, True, 0, f"前台已存在商品，視為成功")
                        success_this_round.append(pname)
                    else:
                        still_fail.append((pname, errmsg))
                else:
                    still_fail.append((pname, errmsg))

            # 4. 更新
            all_success.update(success_this_round)
            all_fail = set(pname for pname, _ in still_fail)
            fail_list_accumulate = still_fail
            retries += 1
            self.all_done_signal.emit(len(all_names), len(all_success), len(all_fail), list(still_fail))

        # 最終emit
        self.all_done_signal.emit(len(all_names), len(all_success), len(all_fail), list(fail_list_accumulate))

    async def _upload_one_product(self, sem, context, pname, info_path, output_path, domain, speed_params):
        async with sem:
            await self._pause_event.wait()
            if self._should_stop:
                return pname, False, "STOP", False
            percent = 0
            self.product_progress_signal.emit(pname, percent, None, None, "開始上架")
            try:
                ok, msg, cf_encountered = await upload_single_product_async(
                    context, info_path, output_path, pname, self.product_progress_signal, domain, speed_params
                )
                percent = 100
                self.product_progress_signal.emit(pname, percent, ok, None, msg)
                return pname, ok, msg, cf_encountered
            except Exception as e:
                percent = 100
                errmsg = f"Exception: {e}"
                self.product_progress_signal.emit(pname, percent, False, None, errmsg)
                return pname, False, errmsg, False
