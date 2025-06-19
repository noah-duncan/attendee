import threading
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GObject

# --------------------------------------------------------------------------- #
#  Core class                                                                 #
# --------------------------------------------------------------------------- #
class MP4Demuxer:
    """
    Stream-demux a remote MP4.

    Parameters
    ----------
    url : str
        Full HTTP/HTTPS URL of the MP4.
    on_video_sample : Callable[[float, bytes], None]
        Called with (pts_seconds, raw_rgba_frame).
    on_audio_sample : Callable[[float, bytes], None]
        Called with (pts_seconds, raw_pcm_block).
    """

    def __init__(self, url, output_video_dimensions, on_video_sample, on_audio_sample):
        Gst.init(None)
        self._url = url
        self._video_cb = on_video_sample
        self._audio_cb = on_audio_sample
        self._output_video_dimensions = output_video_dimensions
        self._playing = False
        self._loop = GObject.MainLoop()
        self._thread = None

        self._build_pipeline()

    # ------------------------------------------------------------------ #
    #  Public control API                                                #
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """
        Start streaming in a background GLib thread.
        """
        if self._playing:
            return
        self._pipeline.set_state(Gst.State.PLAYING)
        self._thread = threading.Thread(target=self._loop.run, daemon=True)
        self._thread.start()
        self._playing = True

    def stop(self) -> None:
        """
        Stop playback and free resources.
        """
        if not self._playing:
            return
        self._pipeline.send_event(Gst.Event.new_eos())  # graceful EOS
        self._pipeline.set_state(Gst.State.NULL)
        self._loop.quit()
        if self._thread and self._thread.is_alive():
            self._thread.join()
        self._playing = False

    def is_playing(self) -> bool:
        """
        Returns True while the pipeline is running.
        """
        return self._playing

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                  #
    # ------------------------------------------------------------------ #
    def _build_pipeline(self) -> None:
        """
        Create elements, link them, and attach callbacks.
        """
        launch = f"""
            uridecodebin name=d uri={self._url}

                d. ! queue max-size-buffers=1000000 max-size-bytes=2294967200 max-size-time=0 leaky=upstream \
                    ! videoconvert \
                    ! videoscale \
                    ! videorate max-rate=15 drop-only=true \
                    ! video/x-raw,framerate=15/1,width={self._output_video_dimensions[0]},height={self._output_video_dimensions[1]},format=I420 \
                    ! appsink name=vsink emit-signals=true sync=true max-buffers=100 drop=true

                d. ! queue max-size-buffers=1000000 max-size-bytes=100000000 max-size-time=0 leaky=upstream \
                    ! audioconvert \
                    ! audioresample \
                    ! audio/x-raw,format=S16LE,channels=1,rate=8000 \
                    ! appsink name=asink emit-signals=true sync=true max-buffers=300 drop=true
        """
        self._pipeline = Gst.parse_launch(launch)

        # sink elements
        vsink = self._pipeline.get_by_name("vsink")
        asink = self._pipeline.get_by_name("asink")

        # connect data callbacks
        vsink.connect("new-sample", self._on_video_sample)
        asink.connect("new-sample", self._on_audio_sample)

        # bus watch to stop on EOS / ERROR
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    # ------------------------- Sample handlers ------------------------- #
    def _on_video_sample(self, sink) -> Gst.FlowReturn:
        return self._dispatch_sample(sink, self._video_cb)

    def _on_audio_sample(self, sink) -> Gst.FlowReturn:
        return self._dispatch_sample(sink, self._audio_cb)

    def _dispatch_sample(self, sink, user_cb):
        if user_cb is None:
            return Gst.FlowReturn.OK

        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        buf = sample.get_buffer()
        pts = buf.pts / Gst.SECOND
        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if success:
            try:
                user_cb(pts, bytes(mapinfo.data))
            finally:
                buf.unmap(mapinfo)

        return Gst.FlowReturn.OK

    # ------------------------- Bus handler ----------------------------- #
    def _on_bus_message(self, bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS or t == Gst.MessageType.ERROR:
            # Pipeline finished or hit error – shut down cleanly
            self.stop()