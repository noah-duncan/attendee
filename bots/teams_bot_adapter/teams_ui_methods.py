import logging
import time

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from bots.web_bot_adapter.ui_methods import UiCouldNotClickElementException, UiCouldNotJoinMeetingWaitingRoomTimeoutException, UiCouldNotLocateElementException, UiRequestToJoinDeniedException, UiRetryableExpectedException

logger = logging.getLogger(__name__)


class UiTeamsBlockingUsException(UiRetryableExpectedException):
    def __init__(self, message, step=None, inner_exception=None):
        super().__init__(message, step, inner_exception)


class TeamsUIMethods:
    def __init__(self, driver, meeting_url, display_name):
        self.driver = driver
        self.meeting_url = meeting_url
        self.display_name = display_name

    def locate_element(self, step, condition, wait_time_seconds=60):
        try:
            element = WebDriverWait(self.driver, wait_time_seconds).until(condition)
            return element
        except Exception as e:
            logger.info(f"Exception raised in locate_element for {step}")
            raise UiCouldNotLocateElementException(f"Exception raised in locate_element for {step}", step, e)

    def find_element_by_selector(self, selector_type, selector):
        try:
            return self.driver.find_element(selector_type, selector)
        except NoSuchElementException:
            return None
        except Exception as e:
            logger.info(f"Unknown error occurred in find_element_by_selector. Exception type = {type(e)}")
            return None

    def click_element(self, element, step):
        try:
            element.click()
        except Exception as e:
            logger.info(f"Error occurred when clicking element {step}, will retry")
            raise UiCouldNotClickElementException("Error occurred when clicking element", step, e)

    def look_for_waiting_to_be_admitted_element(self, step):
        waiting_element = self.find_element_by_selector(By.XPATH, '//*[contains(text(), "Someone will let you in soon")]')
        if waiting_element:
            # Check if we've been waiting too long
            logger.info("Still waiting to be admitted to the meeting after waiting period expired. Raising UiRequestToJoinDeniedException")
            raise UiRequestToJoinDeniedException("Bot was not let in after waiting period expired", step)

    def turn_off_media_inputs(self):
        logger.info("Waiting for the microphone button...")
        microphone_button = self.locate_element(step="turn_off_microphone_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="toggle-mute"]')), wait_time_seconds=6)
        logger.info("Clicking the microphone button...")
        self.click_element(microphone_button, "turn_off_microphone_button")

        logger.info("Waiting for the camera button...")
        camera_button = self.locate_element(step="turn_off_camera_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="toggle-video"]')), wait_time_seconds=6)
        logger.info("Clicking the camera button...")
        self.click_element(camera_button, "turn_off_camera_button")

    def fill_out_name_input(self):
        num_attempts = 30
        logger.info("Waiting for the name input field...")
        for attempt_index in range(num_attempts):
            try:
                name_input = WebDriverWait(self.driver, 1).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="prejoin-display-name-input"]')))
                logger.info("Name input found")
                name_input.send_keys(self.display_name)
                return
            except TimeoutException as e:
                last_check_timed_out = attempt_index == num_attempts - 1
                if last_check_timed_out:
                    logger.info("Could not find name input. Timed out. Raising UiCouldNotLocateElementException")
                    raise UiCouldNotLocateElementException("Could not find name input. Timed out.", "name_input", e)
            except Exception as e:
                logger.info(f"Could not find name input. Unknown error {e} of type {type(e)}. Raising UiCouldNotLocateElementException")
                raise UiCouldNotLocateElementException("Could not find name input. Unknown error.", "name_input", e)

    def click_captions_button(self):
        logger.info("Enabling closed captions programatically...")
        closed_caption_enable_result = self.driver.execute_script("return window.callManager?.enableClosedCaptions()")
        if closed_caption_enable_result:
            logger.info("Closed captions enabled programatically")
            return

        logger.info("Failed to enable closed captions programatically. Waiting for the Language and Speech button...")
        try:
            language_and_speech_button = self.locate_element(step="language_and_speech_button", condition=EC.presence_of_element_located((By.ID, "LanguageSpeechMenuControl-id")), wait_time_seconds=4)
            logger.info("Clicking the language and speech button...")
            self.click_element(language_and_speech_button, "language_and_speech_button")
        except Exception:
            logger.info("Unable to find language and speech button. Exception will be caught because the caption button may be directly visible instead.")

        logger.info("Waiting for the closed captions button...")
        closed_captions_button = self.locate_element(step="closed_captions_button", condition=EC.presence_of_element_located((By.ID, "closed-captions-button")), wait_time_seconds=10)
        logger.info("Clicking the closed captions button...")
        self.click_element(closed_captions_button, "closed_captions_button")

    def set_caption_language_to_italian(self):        
        """Set the caption language to Italian after captions have been enabled"""
        logger.info("Setting caption language to Italian...")
        
        # Step 1: Click the captions settings menu trigger button using data-tid
        logger.info("Waiting for the captions settings menu trigger button...")
        captions_settings_trigger = self.locate_element(
            step="captions_settings_trigger", 
            condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="closed-captions-settings-menu-trigger-button"]')), 
            wait_time_seconds=10
        )
        logger.info("Clicking the captions settings menu trigger button...")
        self.click_element(captions_settings_trigger, "captions_settings_trigger")
        
        # Add a small delay for menu to appear
        time.sleep(2)
        
        # Look for the actual language dropdown button (not just the title)
        logger.info("Looking for language dropdown button in settings panel...")
        
        # Try to find the actual dropdown button near the "Caption language" text
        language_dropdown_selectors = [
            # Look for dropdown button by ID (common pattern is title + button)
            (By.ID, "callingcaptions-subtitles-language-dropdown", "language dropdown button by ID"),
            (By.XPATH, "//span[@id='callingcaptions-subtitles-language-dropdown-title']/following-sibling::button", "button after title"),
            (By.XPATH, "//span[@id='callingcaptions-subtitles-language-dropdown-title']/..//button", "button in same container as title"),
            (By.XPATH, "//span[contains(text(), 'Caption language')]/..//button", "button near Caption language text"),
            (By.XPATH, "//span[contains(text(), 'Caption language')]/following-sibling::*[@role='combobox']", "combobox after Caption language"),
            (By.CSS_SELECTOR, "[role='combobox'][id*='language']", "language combobox by role"),
            (By.CSS_SELECTOR, "button[id*='language'][id*='dropdown']", "language dropdown button"),
            (By.XPATH, "//div[contains(@class, 'dropdown')]//button[contains(@id, 'language')]", "language button in dropdown class"),
        ]
        
        language_dropdown = None
        
        for selector_type, selector, description in language_dropdown_selectors:
            try:
                logger.info(f"Trying to find language dropdown using: {description}")
                elements = self.driver.find_elements(selector_type, selector)
                logger.info(f"  Found {len(elements)} elements with this selector")
                
                if elements:
                    for elem in elements:
                        try:
                            if elem.is_displayed() and elem.is_enabled():
                                logger.info(f"  Found visible/enabled language element: {elem.tag_name}, ID: '{elem.get_attribute('id')}', role: '{elem.get_attribute('role')}'")
                                language_dropdown = elem
                                break
                        except:
                            continue
                    
                    if language_dropdown:
                        break
                        
            except Exception as e:
                logger.info(f"  Error with selector {description}: {e}")
                continue
        
        if not language_dropdown:
            # Debug what's actually available around the Caption language text
            logger.info("=== DEBUGGING AROUND CAPTION LANGUAGE TEXT ===")
            try:
                caption_lang_span = self.driver.find_element(By.ID, "callingcaptions-subtitles-language-dropdown-title")
                parent = caption_lang_span.find_element(By.XPATH, "../..")
                
                logger.info("Elements in the caption language section:")
                all_elements = parent.find_elements(By.XPATH, ".//*")
                for i, elem in enumerate(all_elements[:15]):  # Limit to first 15
                    try:
                        logger.info(f"  {i+1}. {elem.tag_name}, ID: '{elem.get_attribute('id')}', role: '{elem.get_attribute('role')}', class: '{elem.get_attribute('class')[:50]}', text: '{elem.text[:30]}', visible: {elem.is_displayed()}")
                    except:
                        logger.info(f"  {i+1}. Could not get element details")
                        
            except Exception as e:
                logger.info(f"Error debugging caption language section: {e}")
            logger.info("=== END DEBUGGING ===")
            
            logger.info("Could not find language dropdown button. Looking for any clickable language elements...")
            
            # Try to find any clickable element that might be the language selector
            fallback_selectors = [
                (By.XPATH, "//*[contains(@id, 'language') and (@role='button' or @role='combobox' or contains(@class, 'dropdown'))]", "any language clickable"),
                (By.XPATH, "//div[contains(@class, 'dropdown') or contains(@class, 'select')]//button", "any dropdown/select button"),
                (By.XPATH, "//*[@role='combobox']", "any combobox"),
                (By.CSS_SELECTOR, "select", "any select element"),
            ]
            
            for selector_type, selector, description in fallback_selectors:
                try:
                    logger.info(f"Fallback search using: {description}")
                    elements = self.driver.find_elements(selector_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            logger.info(f"  Found: {elem.tag_name}, ID: '{elem.get_attribute('id')}', role: '{elem.get_attribute('role')}'")
                            # Check if this element is in the language section
                            if 'language' in elem.get_attribute('id').lower() or 'language' in elem.get_attribute('class').lower():
                                language_dropdown = elem
                                break
                    if language_dropdown:
                        break
                except Exception as e:
                    logger.info(f"  Error with fallback {description}: {e}")
        
        if not language_dropdown:
            logger.info("Could not find language dropdown. The language settings might work differently.")
            raise UiCouldNotLocateElementException("Could not find language dropdown", "language_dropdown")
        
        logger.info(f"Clicking the language dropdown: {language_dropdown.tag_name} with ID '{language_dropdown.get_attribute('id')}'")
        self.click_element(language_dropdown, "language_dropdown")
        
        # Wait a moment for dropdown options to appear
        time.sleep(2)
        
        # Debug what appears after clicking the dropdown
        logger.info("=== DEBUGGING AFTER DROPDOWN CLICK ===")
        try:
            # Look for any new elements that might be language options
            all_visible_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Italian') or contains(text(), 'Italiano') or contains(text(), 'Italia')]")
            logger.info(f"Found {len(all_visible_elements)} elements with Italian text:")
            for i, elem in enumerate(all_visible_elements[:10]):
                try:
                    if elem.is_displayed():
                        logger.info(f"  {i+1}. {elem.tag_name}, text: '{elem.text}', ID: '{elem.get_attribute('id')}', role: '{elem.get_attribute('role')}'")
                except:
                    continue
                    
            # Look for option elements
            option_elements = self.driver.find_elements(By.XPATH, "//*[@role='option'] | //option | //li")
            visible_options = [elem for elem in option_elements if elem.is_displayed()]
            logger.info(f"Found {len(visible_options)} visible option-like elements:")
            for i, elem in enumerate(visible_options[:10]):
                try:
                    logger.info(f"  {i+1}. {elem.tag_name}, text: '{elem.text[:50]}', role: '{elem.get_attribute('role')}'")
                except:
                    continue
                    
        except Exception as e:
            logger.info(f"Error during post-dropdown debugging: {e}")
        logger.info("=== END POST-DROPDOWN DEBUGGING ===")
        
        # Step 2: Look for Italian language option
        logger.info("Looking for Italian language option...")
        italian_option_selectors = [
            (By.XPATH, "//*[@role='option' and contains(text(), 'Italiano')]", "Italian role option"),
            (By.XPATH, "//option[contains(text(), 'Italiano') or contains(text(), 'Italian')]", "Italian option element"),
            (By.XPATH, "//li[contains(text(), 'Italiano') or contains(text(), 'Italian')]", "Italian li element"),
            (By.XPATH, "//*[contains(text(), 'Italiano (Italia)')]", "Italian Italia text"),
            (By.XPATH, "//*[contains(text(), 'Italian')]", "Italian text"),
            (By.XPATH, "//div[contains(@class, 'option') and contains(text(), 'Italiano')]", "Italian div option"),
            (By.CSS_SELECTOR, "option[value*='it'], option[value*='ita']", "Italian option by value"),
        ]
        
        italian_option = None
        
        for selector_type, selector, description in italian_option_selectors:
            try:
                logger.info(f"Looking for Italian option using: {description}")
                elements = self.driver.find_elements(selector_type, selector)
                logger.info(f"  Found {len(elements)} elements")
                
                if elements:
                    for elem in elements:
                        try:
                            if elem.is_displayed() and elem.is_enabled():
                                logger.info(f"  Found visible/enabled Italian option: {elem.text}")
                                italian_option = elem
                                break
                        except:
                            continue
                    
                    if italian_option:
                        break
                        
            except Exception as e:
                logger.info(f"  Error with Italian selector {description}: {e}")
                continue
        
        if not italian_option:
            logger.info("Could not find Italian language option after clicking dropdown")
            raise UiCouldNotLocateElementException("Could not find Italian language option", "italian_language_option")
        
        logger.info("Clicking the Italian language option...")
        self.click_element(italian_option, "italian_language_option")
        
        logger.info("Caption language successfully set to Italian")
        
        
    def check_if_waiting_room_timeout_exceeded(self, waiting_room_timeout_started_at, step):
        waiting_room_timeout_exceeded = time.time() - waiting_room_timeout_started_at > self.automatic_leave_configuration.waiting_room_timeout_seconds
        if waiting_room_timeout_exceeded:
            # If there is more than one participant in the meeting, then the bot was just let in and we should not timeout
            if len(self.participants_info) > 1:
                logger.info("Waiting room timeout exceeded, but there is more than one participant in the meeting. Not aborting join attempt.")
                return

            try:
                self.click_cancel_join_button()
            except Exception:
                logger.info("Error clicking cancel join button, but not a fatal error")

            self.abort_join_attempt()
            logger.info("Waiting room timeout exceeded. Raising UiCouldNotJoinMeetingWaitingRoomTimeoutException")
            raise UiCouldNotJoinMeetingWaitingRoomTimeoutException("Waiting room timeout exceeded", step)

    def click_show_more_button(self):
        waiting_room_timeout_started_at = time.time()
        num_attempts = self.automatic_leave_configuration.waiting_room_timeout_seconds * 10
        logger.info("Waiting for the show more button...")
        for attempt_index in range(num_attempts):
            try:
                show_more_button = WebDriverWait(self.driver, 1).until(EC.presence_of_element_located((By.ID, "callingButtons-showMoreBtn")))
                logger.info("Clicking the show more button...")
                self.click_element(show_more_button, "click_show_more_button")
                return
            except TimeoutException:
                self.look_for_denied_your_request_element("click_show_more_button")
                self.look_for_we_could_not_connect_you_element("click_show_more_button")

                self.check_if_waiting_room_timeout_exceeded(waiting_room_timeout_started_at, "click_show_more_button")

            except Exception as e:
                logger.info("Exception raised in locate_element for show_more_button")
                raise UiCouldNotLocateElementException("Exception raised in locate_element for click_show_more_button", "click_show_more_button", e)

    def look_for_we_could_not_connect_you_element(self, step):
        we_could_not_connect_you_element = self.find_element_by_selector(By.XPATH, '//*[contains(text(), "we couldn\'t connect you")]')
        if we_could_not_connect_you_element:
            logger.info("Teams is blocking us for whatever reason, but we can retry. Raising UiTeamsBlockingUsException")
            raise UiTeamsBlockingUsException("Teams is blocking us for whatever reason, but we can retry", step)

    def look_for_denied_your_request_element(self, step):
        denied_your_request_element = self.find_element_by_selector(
            By.XPATH,
            '//*[contains(text(), "but you were denied access to the meeting") or contains(text(), "Your request to join was declined")]',
        )

        if denied_your_request_element:
            logger.info("Someone in the call denied our request to join. Raising UiRequestToJoinDeniedException")
            dismiss_button = self.locate_element(step="closed_captions_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="calling-retry-cancelbutton"]')), wait_time_seconds=2)
            if dismiss_button:
                logger.info("Clicking the dismiss button...")
                self.click_element(dismiss_button, "dismiss_button")
            raise UiRequestToJoinDeniedException("Someone in the call denied your request to join", step)

    def select_speaker_view(self):
        logger.info("Waiting for the view button...")
        view_button = self.locate_element(step="view_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, "#view-mode-button, #custom-view-button")), wait_time_seconds=60)
        logger.info("Clicking the view button...")
        self.click_element(view_button, "view_button")

        logger.info("Waiting for the speaker view button...")
        speaker_view_button = self.locate_element(step="speaker_view_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, "#custom-view-button-SpeakerViewButton, #SpeakerView-button")), wait_time_seconds=10)
        logger.info("Clicking the speaker view button...")
        self.click_element(speaker_view_button, "speaker_view_button")

    # Returns nothing if succeeded, raises an exception if failed
    def attempt_to_join_meeting(self):
        self.driver.get(self.meeting_url)

        self.driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": self.meeting_url,
                "permissions": [
                    "geolocation",
                    "audioCapture",
                    "displayCapture",
                    "videoCapture",
                ],
            },
        )

        self.fill_out_name_input()

        self.turn_off_media_inputs()

        logger.info("Waiting for the Join now button...")
        join_button = self.locate_element(step="join_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="prejoin-join-button"]')), wait_time_seconds=10)
        logger.info("Clicking the Join now button...")
        self.click_element(join_button, "join_button")

        # Wait for meeting to load and enable captions
        self.click_show_more_button()

        # Click the captions button
        self.click_captions_button()

        # Set caption language to Italian
        self.set_caption_language_to_italian()

        # Select speaker view
        self.select_speaker_view()

        self.ready_to_show_bot_image()

    def click_leave_button(self):
        logger.info("Waiting for the leave button")
        leave_button = WebDriverWait(self.driver, 6).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    '[data-inp="hangup-button"], #hangup-button',
                )
            )
        )

        logger.info("Clicking the leave button")
        leave_button.click()

    def click_cancel_join_button(self):
        logger.info("Waiting for the cancel button...")
        cancel_button = self.locate_element(step="cancel_button", condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="prejoin-cancel-button"]')), wait_time_seconds=10)
        logger.info("Clicking the cancel button...")
        self.click_element(cancel_button, "cancel_button")