from dataclasses import dataclass


@dataclass(frozen=True)
class AutomaticLeaveConfiguration:
    """Specifies conditions under which the bot will automatically leave a meeting.

    Attributes:
        silence_threshold_seconds: Number of seconds of continuous silence after which the bot should leave
        only_participant_in_meeting_threshold_seconds: Number of seconds to wait before leaving if bot is the only participant
        wait_for_host_to_start_meeting_timeout_seconds: Number of seconds to wait for the host to start the meeting
        silence_activate_after_seconds: Number of seconds to wait before activating the silence threshold
    """

    silence_threshold_seconds: int = 600
    only_participant_in_meeting_threshold_seconds: int = 60
    wait_for_host_to_start_meeting_timeout_seconds: int = 600
    silence_activate_after_seconds: int = 1200
