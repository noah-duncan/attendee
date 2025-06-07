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
        
        # Click the captions settings trigger button
        logger.info("Waiting for the captions settings menu trigger button...")
        captions_settings_trigger = self.locate_element(
            step="captions_settings_trigger", 
            condition=EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="closed-captions-settings-menu-trigger-button"]')), 
            wait_time_seconds=10
        )
        logger.info("Clicking the captions settings menu trigger button...")
        self.click_element(captions_settings_trigger, "captions_settings_trigger")
        
        # Wait for settings menu to appear
        time.sleep(1)
        
        # Find and click the language dropdown
        logger.info("Waiting for the language dropdown...")
        language_dropdown = self.locate_element(
            step="language_dropdown",
            condition=EC.presence_of_element_located((By.XPATH, "//span[@id='callingcaptions-subtitles-language-dropdown-title']/..//button[@role='combobox']")),
            wait_time_seconds=10
        )
        logger.info("Clicking the language dropdown...")
        self.click_element(language_dropdown, "language_dropdown")
        
        # Wait for dropdown options to appear
        time.sleep(1)
        
        # Find and click the Italian option
        logger.info("Waiting for the Italian language option...")
        italian_option = self.locate_element(
            step="italian_language_option",
            condition=EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Italian')]")),
            wait_time_seconds=10
        )
        logger.info("Clicking the Italian language option...")
        self.click_element(italian_option, "italian_language_option")
        
        logger.info("Caption language successfully set to Italian")

    def check_if_waiting_room_timeout_exceeded(self, waiting_room_timeout_started_at, step):
        try:
            timeout_seconds = self.automatic_leave_configuration.waiting_room_timeout_seconds
            waiting_room_timeout_exceeded = time.time() - waiting_room_timeout_started_at > timeout_seconds
            
            if waiting_room_timeout_exceeded:
                try:
                    if len(self.participants_info) > 1:
                        logger.info("Waiting room timeout exceeded, but there is more than one participant in the meeting. Not aborting join attempt.")
                        return
                except (AttributeError, TypeError):
                    pass

                try:
                    self.click_cancel_join_button()
                except Exception:
                    logger.info("Error clicking cancel join button, but not a fatal error")

                try:
                    self.abort_join_attempt()
                except AttributeError:
                    logger.info("abort_join_attempt method not found")

                logger.info("Waiting room timeout exceeded. Raising UiCouldNotJoinMeetingWaitingRoomTimeoutException")
                raise UiCouldNotJoinMeetingWaitingRoomTimeoutException("Waiting room timeout exceeded", step)
        except AttributeError:
            logger.info("automatic_leave_configuration not found, skipping timeout check")

    def click_show_more_button(self):
        waiting_room_timeout_started_at = time.time()
        
        try:
            timeout_seconds = self.automatic_leave_configuration.waiting_room_timeout_seconds
            num_attempts = timeout_seconds * 10
        except AttributeError:
            logger.info("automatic_leave_configuration not found, using default timeout")
            timeout_seconds = 60
            num_attempts = 600
        
        logger.info("Waiting for the show more button...")
        for attempt_index in range(num_attempts):
            try:
                show_more_button = WebDriverWait(self.driver, 1).until(EC.presence_of_element_located((By.ID, "callingButtons-showMoreBtn")))
                logger.info("Clicking the show more button...")
                self.click_element(show_more_button, "click_show_more_button")
                return
            except TimeoutException:
                try:
                    self.look_for_denied_your_request_element("click_show_more_button")
                    self.look_for_we_could_not_connect_you_element("click_show_more_button")
                    self.check_if_waiting_room_timeout_exceeded(waiting_room_timeout_started_at, "click_show_more_button")
                except AttributeError:
                    # Methods might not exist, continue with simple timeout check
                    if time.time() - waiting_room_timeout_started_at > timeout_seconds:
                        logger.info("Timeout waiting for show more button")
                        raise UiCouldNotLocateElementException("Timeout waiting for show more button", "click_show_more_button")

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

    def attempt_to_join_meeting(self):
        """Returns nothing if succeeded, raises an exception if failed"""
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
        self.click_captions_button()
        
        # Set caption language to Italian
        try:
            self.set_caption_language_to_italian()
        except Exception as e:
            logger.warning(f"Could not set caption language to Italian: {e}")
            logger.info("Continuing with default caption language - captions are still enabled")

        # Select speaker view
        self.select_speaker_view()

        # Call ready_to_show_bot_image if it exists
        try:
            self.ready_to_show_bot_image()
        except AttributeError:
            logger.info("ready_to_show_bot_image method not found, continuing...")
        except Exception as e:
            logger.warning(f"Error in ready_to_show_bot_image: {e}")

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