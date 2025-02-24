class BotAdapter:
    class Messages:
        LEAVE_MEETING_WAITING_FOR_HOST = "Leave meeting because received waiting for host status"
        ZOOM_AUTHORIZATION_FAILED = "Zoom authorization failed"
        ZOOM_MEETING_STATUS_FAILED = "Zoom meeting status failed"
        ZOOM_MEETING_STATUS_FAILED_UNABLE_TO_JOIN_EXTERNAL_MEETING = "Zoom meeting status failed - unable to join external meeting"
        ZOOM_SDK_INTERNAL_ERROR = "Zoom SDK Internal Error"
        BOT_PUT_IN_WAITING_ROOM = "Bot put in waiting room"
        BOT_JOINED_MEETING = "Bot joined meeting"
        BOT_RECORDING_PERMISSION_GRANTED = "Bot recording permission granted"
        MEETING_ENDED = "Meeting ended"
        NEW_UTTERANCE = "New utterance"
        UI_ELEMENT_NOT_FOUND = "UI Element Not Found"
        REQUEST_TO_JOIN_DENIED = "Request to join denied"
        ADAPTER_REQUESTED_BOT_LEAVE_MEETING = "Adapter requested bot leave meeting"

    class LEAVE_REASON:
        AUTO_LEAVE_SILENCE = "AUTO_LEAVE_SILENCE"
        AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING = "AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING"