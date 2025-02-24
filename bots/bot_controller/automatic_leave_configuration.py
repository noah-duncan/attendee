from dataclasses import dataclass


@dataclass(frozen=True)
class AutomaticLeaveConfiguration:
    """Specifies conditions under which the bot will automatically leave a meeting.
    
    Attributes:
        silence_threshold_seconds: Number of seconds of continuous silence after which the bot should leave
        only_participant_in_meeting_threshold_seconds: Number of seconds to wait before leaving if bot is the only participant
    """
    silence_threshold_seconds: int = 300
    only_participant_in_meeting_threshold_seconds: int = 60
    wait_for_host_to_start_meeting_timeout_seconds: int = 120