import os

import undetected_chromedriver as uc
from django.test.testcases import TransactionTestCase
from pyvirtualdisplay import Display


class TestChromeDriver(TransactionTestCase):
    def test_can_open_google(self):
        # Create virtual display if no real display is available
        if os.environ.get("DISPLAY") is None:
            display = Display(visible=0, size=(1920, 1080))
            display.start()

        try:
            # Set up Chrome options
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-setuid-sandbox")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-application-cache")
            options.add_argument("--disable-dev-shm-usage")

            # Initialize Chrome driver
            driver = uc.Chrome(use_subprocess=True, options=options, version_main=133)

            try:
                # Load Google
                driver.get("https://www.google.com")

                # Verify we can find the Google search box
                search_box = driver.find_element("name", "q")

                # Basic assertion that we found the search box
                self.assertIsNotNone(search_box)

            finally:
                # Clean up driver
                driver.quit()

        except Exception as e:
            self.fail(f"Failed to open Chrome and load Google: {str(e)}")
