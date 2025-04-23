import logging

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from bots.web_bot_adapter.ui_methods import UiCouldNotClickElementException, UiCouldNotLocateElementException, UiRequestToJoinDeniedException

logger = logging.getLogger(__name__)


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

    def look_for_denied_request_element(self, step):
        denied_request_element = self.find_element_by_selector(By.XPATH, '//*[contains(text(), "Your request to join was declined")]')
        if denied_request_element:
            logger.info("The request to join the Teams meeting was declined. Raising UiRequestToJoinDeniedException")
            raise UiRequestToJoinDeniedException("The request to join the Teams meeting was declined", step)

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
        logger.info("Waiting for the show more button...")
        show_more_button = self.locate_element(step="show_more_button", condition=EC.presence_of_element_located((By.ID, "callingButtons-showMoreBtn")), wait_time_seconds=60)
        logger.info("Clicking the show more button...")
        self.click_element(show_more_button, "show_more_button")

        logger.info("Waiting for the Language and Speech button...")
        language_and_speech_button = self.locate_element(step="language_and_speech_button", condition=EC.presence_of_element_located((By.ID, "LanguageSpeechMenuControl-id")), wait_time_seconds=10)
        logger.info("Clicking the language and speech button...")
        self.click_element(language_and_speech_button, "language_and_speech_button")

        logger.info("Waiting for the closed captions button...")
        closed_captions_button = self.locate_element(step="closed_captions_button", condition=EC.presence_of_element_located((By.ID, "closed-captions-button")), wait_time_seconds=10)
        logger.info("Clicking the closed captions button...")
        self.click_element(closed_captions_button, "closed_captions_button")

    def select_speaker_view(self):
        logger.info("Waiting for the view button...")
        view_button = self.locate_element(step="view_button", condition=EC.presence_of_element_located((By.ID, "view-mode-button")), wait_time_seconds=60)
        logger.info("Clicking the view button...")
        self.click_element(view_button, "view_button")

        logger.info("Waiting for the speaker view button...")
        speaker_view_button = self.locate_element(step="speaker_view_button", condition=EC.presence_of_element_located((By.ID, "custom-view-button-SpeakerViewButton")), wait_time_seconds=10)
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

        # Check if we were denied entry
        try:
            WebDriverWait(self.driver, 10).until(lambda d: self.look_for_denied_request_element("join_meeting") or False)
        except TimeoutException:
            pass  # This is expected if we're not denied

        # Wait for meeting to load and enable captions
        self.click_captions_button()

        # Select speaker view
        self.select_speaker_view()

        self.ready_to_show_bot_image()

    def click_leave_button(self):
        logger.info("Waiting for the leave button")
        leave_button = WebDriverWait(self.driver, 6).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    '[data-inp="hangup-button"]',
                )
            )
        )

        logger.info("Clicking the leave button")
        leave_button.click()
