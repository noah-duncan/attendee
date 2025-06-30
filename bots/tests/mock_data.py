import time


class MockVideoFrame:
    def __init__(self):
        width = 640
        height = 360

        # Create separate Y, U, and V planes
        self.y_buffer = b"\x00" * (width * height)  # Y plane (black)
        self.u_buffer = b"\x80" * (width * height // 4)  # U plane (128 for black)
        self.v_buffer = b"\x80" * (width * height // 4)  # V plane (128 for black)

        self.size = len(self.y_buffer) + len(self.u_buffer) + len(self.v_buffer)
        self.timestamp = int(time.time() * 1000)  # Current time in milliseconds

    def GetBuffer(self):
        return self.y_buffer + self.u_buffer + self.v_buffer

    def GetYBuffer(self):
        return self.y_buffer

    def GetUBuffer(self):
        return self.u_buffer

    def GetVBuffer(self):
        return self.v_buffer

    def GetStreamWidth(self):
        return 640

    def GetStreamHeight(self):
        return 360


class MockPCMAudioFrame:
    def __init__(self):
        # Create 10ms of a 440Hz sine wave at 32000Hz mono
        # 32000 samples/sec * 0.01 sec = 320 samples
        # Each sample is 2 bytes (unsigned 16-bit)
        import math

        samples = []
        for i in range(320):  # 10ms worth of samples at 32kHz
            # Generate sine wave with frequency 440Hz
            t = i / 32000.0  # time in seconds
            # Generate value between 0 and 65535 (unsigned 16-bit)
            # Center at 32768, use amplitude of 16384 to avoid clipping
            value = int(32768 + 16384 * math.sin(2 * math.pi * 440 * t))
            # Ensure value stays within valid range
            value = max(0, min(65535, value))
            # Convert to two bytes (little-endian)
            samples.extend([value & 0xFF, (value >> 8) & 0xFF])
        self.buffer = bytes(samples)

    def GetBuffer(self):
        return self.buffer

    def GetSampleRate(self):
        return 32000

    def GetChannelNum(self):
        return 1


class MockF32AudioFrame:
    def __init__(self):
        # Create 10ms of a 440Hz sine wave at 48000Hz mono
        # 48000 samples/sec * 0.01 sec = 480 samples
        # Each sample is a 32-bit float between -1.0 and 1.0
        import math
        import struct

        samples = []
        for i in range(480):  # 10ms worth of samples at 48kHz
            # Generate sine wave with frequency 440Hz
            t = i / 48000.0  # time in seconds
            # Generate value between -1.0 and 1.0
            value = 0.8 * math.sin(2 * math.pi * 440 * t)  # Using 0.8 amplitude to avoid clipping
            # Pack float to bytes (4 bytes per sample)
            samples.extend(struct.pack("f", value))
        self.buffer = bytes(samples)

    def GetBuffer(self):
        return self.buffer
